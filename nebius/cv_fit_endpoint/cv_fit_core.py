"""Core CV-to-Market Fit matching for the optional /cv-fit endpoint.

This is FastAPI-free on purpose so it can be unit-tested and run with only the
standard library (in the TF-IDF fallback). It reuses the SAME role ontology,
tokenizer, and matcher as the static site (scripts/build_cv_match_index.py), so
the endpoint and the static website stay on one contract:

    vectorize -> cosine similarity -> rerank -> report

Embedding backend (env-gated, see README.md):
  - CV_FIT_EMBEDDING_MODEL set + sentence-transformers importable
        -> neural multilingual embeddings (BGE-M3 / Qwen3): the high-quality path
  - otherwise
        -> the static site's reproducible TF-IDF vector space (no heavy deps)

Privacy: the CV text is processed in-memory per request and never written to
disk or logged. No secrets, no credentials, no storage.
"""

import json
import math
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))           # nebius/cv_fit_endpoint -> repo
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

# Reuse the static engine's ontology, tokenizer, scoring and bucketing.
import build_cv_match_index as bm  # noqa: E402

# Grounded LLM narrative layer (the Nebius GPU path). Importing is cheap — the
# model only loads when CV_FIT_LLM_MODEL is set.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import cv_fit_llm  # noqa: E402

INDEX_PATH = os.environ.get("CV_FIT_INDEX_PATH", os.path.join(REPO_ROOT, "data", "cv_match_index.json"))
CAREER_PATH = os.environ.get("CV_FIT_CAREER_PATH", os.path.join(REPO_ROOT, "data", "career_reality.json"))
REGIONAL_SPLIT_PATH = os.environ.get("CV_FIT_REGIONAL_SPLIT", os.path.join(REPO_ROOT, "data", "regional_split.json"))
EMBEDDING_MODEL = os.environ.get("CV_FIT_EMBEDDING_MODEL", "").strip()
NEURAL_INDEX_PATH = os.environ.get("CV_FIT_NEURAL_INDEX", os.path.join(HERE, "neural_role_index.json"))

# Display + gap-priority maps (mirror app.js).
CV_PRETTY = {
    "sfmc": "SFMC", "ampscript": "AMPscript", "ssjs": "SSJS", "crm": "CRM", "sql": "SQL",
    "apis": "APIs", "api": "API", "etl": "ETL", "kpi": "KPI", "seo": "SEO", "bi": "BI",
    "power_bi": "Power BI", "html_css": "HTML/CSS", "cicd": "CI/CD", "devops": "DevOps",
    "data_cloud": "Salesforce Data Cloud", "machine_learning": "Machine learning",
    "marketing_automation": "Marketing automation", "customer_service": "Customer service",
    "office_tools": "Office tools", "account_management": "Account management",
    "data_visualization": "Data visualization", "supply_chain": "Supply chain",
    "driving_license": "Driving licence", "elderly_care": "Elderly care",
    "patient_care": "Patient care", "incident_response": "Incident response",
    "test_automation": "Test automation", "project_management": "Project management",
    "financial_analysis": "Financial analysis", "social_media": "Social media",
    "google_analytics": "Google Analytics", "email_marketing": "Email marketing",
}
CV_WORD_ACRONYM = {"sql": "SQL", "crm": "CRM", "api": "API", "apis": "APIs", "etl": "ETL",
                   "kpi": "KPI", "seo": "SEO", "bi": "BI", "sfmc": "SFMC"}
CV_HARD_GAPS = {
    "sql", "power_bi", "statistics", "python", "dashboards", "etl", "machine_learning",
    "data_visualization", "sfmc", "marketing_automation", "segmentation", "integration",
    "apis", "google_analytics", "seo", "cloud", "docker", "cicd", "test_automation",
    "javascript", "financial_analysis", "accounting", "crm", "excel", "architecture",
}

# Regional outlook proxy (data methodology, not a hidden assumption): some
# occupation fields are not broken out per region in the public ad data, so for
# those domains we read the closest regionally-tracked field as a proxy and
# DISCLOSE it. Domains whose own field has regional data are not listed here.
REGIONAL_PROXY = {
    "crm_martech": ("apaJ_2ja_LuF", "Data/IT"),            # technical martech ≈ the IT labour market
    "digital_marketing": ("9puE_nYg_crq", "Kultur, media, design"),
}


def pretty(skill):
    s = str(skill or "").lower()
    if s in CV_PRETTY:
        return CV_PRETTY[s]
    return " ".join(CV_WORD_ACRONYM.get(w, w[:1].upper() + w[1:]) for w in s.replace("_", " ").split())


def join_list(items):
    items = [i for i in items if i]
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def why_recommendation(profile, domain_name, best, adj, market_signal, region):
    """Compact, fully-derived "Why this recommendation?" lines.

    No hardcoded domain/role text: everything comes from data we already have —
    the CV's extracted skills, the market signal computed from
    career_reality.json (demand / crowding / remote / regional fit), the matched
    role titles, and the optional region. Max 4 short sentences.
    """
    why = []
    signals = [pretty(s) for s in profile.get("skills", [])[:5]]
    titles = [r["title"] for r in best] or [r["title"] for r in adj]
    # 1) CV evidence — concrete signals the CV actually contains.
    if signals and domain_name:
        why.append(f"Your CV matches {domain_name} because it shows {join_list(signals)}.")
    # 2) Market evidence — the existing public job-ad signal, framed honestly.
    if market_signal:
        why.append("Public job-ad signals show " + market_signal.replace(" · ", ", ").lower() + ".")
    # 3) Regional / search strategy + the titles to prioritise.
    if titles:
        primary = titles[0]
        alts = join_list(titles[1:4]) or primary
        if region:
            why.append(f"In {region}, prioritise {join_list(titles[:3])}; if local demand is thin, "
                       "broaden to nearby regions and remote roles.")
        else:
            why.append(f"For smaller local markets, broaden your title search beyond “{primary}” "
                       f"to {alts}, and include remote roles.")
    return why[:4]


class _Engine:
    """Loads the index + career signals once and answers /cv-fit requests."""

    def __init__(self):
        with open(INDEX_PATH, "r", encoding="utf-8") as fh:
            self.index = json.load(fh)
        self.catalog = self.index["roles"]
        self.idf = self.index.get("idf", {})
        self.tfidf_vectors = {r["role_id"]: r.get("vector", {}) for r in self.catalog}
        self.domain_label = self.index.get("domain_label", {})

        # Optional market signals (does not break if absent).
        self.career = {}
        try:
            with open(CAREER_PATH, "r", encoding="utf-8") as fh:
                self.career = json.load(fh)
        except Exception:
            self.career = {}

        # Per-region ad counts by occupation field (for the cross-region outlook).
        self.regional_split = {}
        try:
            with open(REGIONAL_SPLIT_PATH, "r", encoding="utf-8") as fh:
                self.regional_split = json.load(fh)
        except Exception:
            self.regional_split = {}

        # Backend selection. backend_kind: tfidf | neural | error.
        self.backend_kind = "tfidf"
        self.backend = "tfidf-fallback"   # human label (report "backend" field)
        self.model_name = None
        self.embedding_dim = None
        self.neural_error = None
        self._model = None
        self._role_emb = None
        if EMBEDDING_MODEL:
            self._load_neural(EMBEDDING_MODEL)

        # Grounded LLM generation layer (Nebius GPU path). Retrieval above stays
        # deterministic and grounds the model. When the LLM is active it owns the
        # verdict + "why"; the backend label reflects it.
        self.retrieval_backend = self.backend
        self.llm = cv_fit_llm.get_llm() if cv_fit_llm.llm_enabled() else None
        if self.llm and self.llm.ok:
            self.backend = "llm:" + self.llm.model_id
            if self.retrieval_backend == "tfidf-fallback":
                self.retrieval_backend = "tfidf"

    @staticmethod
    def _role_text(role):
        parts = [role["title"]] + role.get("aliases", []) + role.get("terms", []) \
            + role.get("required_skills", []) + role.get("nice_skills", [])
        return " ".join(parts)

    def _load_precomputed_role_emb(self, model_name):
        """Load role vectors precomputed by scripts/build_neural_role_index.py
        (same model) so we skip re-embedding 41 role docs at boot."""
        try:
            with open(NEURAL_INDEX_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return False
        if data.get("model") != model_name:
            return False
        emb = {r["role_id"]: r["vector"] for r in data.get("roles", [])}
        if emb and all(r["role_id"] in emb for r in self.catalog):
            self._role_emb = emb
            print(f"[cv-fit] loaded {len(emb)} precomputed role embeddings from {NEURAL_INDEX_PATH}")
            return True
        return False

    def _load_neural(self, model_name):
        """Load a neural embedding model (e.g. BGE-M3). Fails CLEARLY: if a model
        was requested but cannot load, backend_kind becomes 'error' and the
        endpoint reports it rather than silently pretending neural is active."""
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            self.backend_kind = "error"
            self.neural_error = f"sentence-transformers not importable: {exc.__class__.__name__}"
            print("[cv-fit] NEURAL REQUESTED but " + self.neural_error)
            return
        try:
            self._model = SentenceTransformer(model_name)
            if not self._load_precomputed_role_emb(model_name):
                docs = [self._role_text(r) for r in self.catalog]
                embs = self._model.encode(docs, normalize_embeddings=True)
                self._role_emb = {r["role_id"]: [float(x) for x in embs[i]]
                                  for i, r in enumerate(self.catalog)}
            self.backend_kind = "neural"
            self.model_name = model_name
            self.backend = "neural:" + model_name
            self.embedding_dim = len(next(iter(self._role_emb.values())))
            print(f"[cv-fit] neural backend active: {model_name} "
                  f"(dim={self.embedding_dim}, roles={len(self._role_emb)})")
        except Exception as exc:  # pragma: no cover - model/runtime dependent
            self.backend_kind = "error"
            self.neural_error = f"failed to load '{model_name}': {exc.__class__.__name__}: {exc}"
            self._model = None
            self._role_emb = None
            print("[cv-fit] NEURAL LOAD FAILED: " + self.neural_error)

    # ---- semantic similarity per backend -------------------------------
    def _semantic_scores(self, query_text):
        if self.backend_kind == "error":
            # Do not silently fall back: a requested neural model failed.
            raise RuntimeError("neural backend unavailable: " + (self.neural_error or "unknown"))
        if self._model is not None and self._role_emb is not None:
            qv = [float(x) for x in self._model.encode([query_text], normalize_embeddings=True)[0]]
            return {rid: float(sum(a * b for a, b in zip(qv, ev)))
                    for rid, ev in self._role_emb.items()}
        # TF-IDF fallback: identical to the static site.
        qvec = bm.embed_query(query_text, self.idf)
        return {r["role_id"]: bm.cosine(qvec, self.tfidf_vectors[r["role_id"]])
                for r in self.catalog}

    # ---- rerank (mirror of scripts/build_cv_match_index.rank_roles) ----
    def _rank(self, profile, sem_by_role):
        cv_skills = set(profile["skills"])
        scored = []
        for r in self.catalog:
            sem = sem_by_role.get(r["role_id"], 0.0)
            req = r["required_skills"]
            cov = (sum(1 for s in req if s in cv_skills) / len(req)) if req else 0.0
            gap = bm.SEN_ORDER[r["seniority"]] - bm.SEN_ORDER.get(profile["seniority"], 0)
            sen_pen = 0.12 * gap if gap > 0 else 0.0
            lang_pen = 0.12 if (r["language_sensitive"] and profile["weak_swedish"]) else 0.0
            fit = max(0.0, 0.55 * sem + 0.30 * cov - sen_pen - lang_pen)
            scored.append({
                "role_id": r["role_id"], "title": r["title"], "domain": r["domain"],
                "secondary_domains": r.get("secondary_domains", []),
                "field_id": r["field_id"], "field_label": r["field_label"],
                "seniority": r["seniority"], "semantic": round(sem, 4),
                "coverage": round(cov, 3), "gap": gap, "fit": round(fit, 4),
                "missing": [s for s in req if s not in cv_skills],
                "language_sensitive": r["language_sensitive"], "keywords": r["search_keywords"],
            })
        scored.sort(key=lambda s: s["fit"], reverse=True)
        return scored

    # ---- market signal (mirror of crcBuildSignalLine) ------------------
    def _market_signal(self, field_id, region):
        occs = [o for o in self.career.get("occupations", []) if o.get("field_id") == field_id]
        if not occs:
            return None
        occ = max(occs, key=lambda o: o.get("opportunity_score", 0))
        parts = []
        trend_word = {"rising": "Rising", "stable": "Stable", "declining": "Cooling"}.get(occ.get("demand_trend"))
        if trend_word:
            parts.append(f"{trend_word} demand")
        elif occ.get("demand_level") and occ["demand_level"] != "unknown":
            parts.append(f"{occ['demand_level']} demand")
        if occ.get("crowding_risk") and occ["crowding_risk"] != "unknown":
            parts.append(f"{occ['crowding_risk']} crowding")
        if region:
            sig = self.career.get("regional_field_strength", {}).get(region, {}).get(field_id, {}).get("signal")
            if sig:
                parts.append(f"{sig} regional fit")
        if occ.get("remote_signal") and occ["remote_signal"] != "unknown":
            parts.append(f"{occ['remote_signal']} remote signal")
        return " · ".join(parts) if parts else None

    def _decision_headline(self, profile, best, adjacent, market_signal):
        """Build the prominent decision from verified matcher and market facts."""
        candidates = best or adjacent
        if not candidates:
            return "Your CV does not match a clear role family yet."

        lead = candidates[0]
        role = lead["title"]
        role_row = next((row for row in self.catalog if row["role_id"] == lead["role_id"]), {})
        cv_skills = set(profile.get("skills", []))
        proof = [
            pretty(skill)
            for skill in role_row.get("required_skills", [])
            if skill in cv_skills
        ][:2]
        proof_text = " and ".join(proof) if proof else "relevant experience"
        signal = (market_signal or "").lower()

        if "rising demand" in signal and "high crowding" in signal:
            return (
                f"Prioritise {role}; demand is rising, but high competition means "
                f"leading with quantified {proof_text} results."
            )
        if "high crowding" in signal:
            return (
                f"Prioritise {role}, but treat it as competitive and lead with "
                f"quantified {proof_text} results."
            )
        if "cooling demand" in signal:
            return (
                f"Treat {role} as a selective target and strengthen proof of "
                f"{proof_text} before applying broadly."
            )
        if best:
            return f"Prioritise {role} and lead with measurable {proof_text} results."
        return f"Treat {role} as a stretch role and strengthen {proof_text} first."

    # ---- cross-region demand outlook (facts for the consultant LLM) ----
    def _regional_outlook(self, pdomain, field_id, region):
        """Where the jobs for the CV's field actually are, ranked by ABSOLUTE ad
        volume (not share ratio), so the LLM can say "few roles in your region —
        most are in Stockholm / Västra Götaland, or go remote" from real counts.

        Some occupation fields (e.g. sales/marketing) are not broken out per
        region in the public ad data. For those we read the closest regionally-
        tracked field as a TRANSPARENT proxy (disclosed via data_basis='proxy')
        instead of inventing regional numbers.
        """
        regions = self.regional_split.get("regions", [])
        if not regions:
            return None

        def field_count(region_row, fid):
            for f in region_row.get("occupation_fields", []):
                if f.get("concept_id") == fid:
                    return f.get("count"), f.get("vs_national")
            return None, None

        use_field, proxy_label, basis = field_id, None, "direct"
        present = any(field_count(r, field_id)[0] is not None for r in regions)
        if not present:
            proxy = REGIONAL_PROXY.get(pdomain)
            if not proxy:
                return {"data_basis": "national_only"}
            use_field, proxy_label = proxy
            basis = "proxy"

        rows = []
        for r in regions:
            cnt, vsn = field_count(r, use_field)
            if cnt is not None:
                rows.append((r.get("term"), cnt, round(vsn, 2) if vsn is not None else None))
        if not rows:
            return {"data_basis": "national_only"}
        rows.sort(key=lambda x: x[1], reverse=True)          # by absolute ad volume

        out = {"data_basis": basis,
               "top_regions": [{"region": t, "ads": c, "vs_national": v} for t, c, v in rows[:4]]}
        if proxy_label:
            out["proxy_field"] = proxy_label
        if region:
            ranked = [t for t, _, _ in rows]
            match = next(((t, c, v) for t, c, v in rows if t == region), None)
            n = len(rows)
            if match:
                rank = ranked.index(region) + 1
                # Derived local-market verdict (rank-based) so even a small model
                # gets the reasoning right; the LLM only does the wording.
                local = "strong" if rank <= 3 else ("thin" if rank > (2 * n) // 3 else "moderate")
                out["selected_region"] = {"region": region, "ads": match[1], "vs_national": match[2],
                                          "rank": rank, "of": n, "local_market": local}
            else:
                out["selected_region"] = {"region": region, "ads": 0, "local_market": "thin"}
        return out

    # ---- public entry point --------------------------------------------
    def analyze(self, cv_text, region=None, swedish_level=None, target_role=None):
        profile = bm.extract_cv(cv_text or "")
        if not profile["skills"] and not profile["roles"] and len(bm.tokenize(cv_text or "")) < 4:
            return {
                "main_answer": "Not enough CV information to produce a job-fit report.",
                "primary_domain": None,
                "domain_label": None,
                "best_fit_roles": [],
                "adjacent_roles": [],
                "not_your_main_lane_roles": [],
                "missing_skills": [],
                "cv_improvements": [
                    "Add role titles, skills, tools, language level, and recent work or study history."
                ],
                "search_keywords": [],
                "action_plan_7_day": [
                    "Paste a fuller CV or provide a text-based PDF before using the report."
                ],
                "market_signal": None,
                "backend": self.backend,
                "extracted": {
                    "seniority": profile["seniority"],
                    "domain": None,
                    "tools": [],
                    "languages": profile["languages"],
                },
            }
        if swedish_level in ("native", "good", "basic", "none"):
            profile["swedish"] = swedish_level
            profile["weak_swedish"] = swedish_level in ("none", "basic")
            profile["languages"] = [l for l in profile["languages"] if not l.startswith("Swedish")]
            if swedish_level != "none":
                profile["languages"].append("Swedish (%s)" % swedish_level)

        # Target role (optional) nudges retrieval by joining it to the query.
        query_text = cv_text or ""
        if target_role:
            query_text = query_text + " " + target_role

        sem_by_role = self._semantic_scores(query_text)
        scored = self._rank(profile, sem_by_role)
        pdomain, best, adj, avoid = bm.bucket(profile, scored)

        is_senior = profile["seniority"] == "senior"
        domain_name = self.domain_label.get(pdomain, pdomain)

        if best:
            lead = "strongest for"
            main = f"Your CV is {lead} {domain_name} roles."
        elif adj:
            main = f"Your CV is close to {self.domain_label.get(adj[0]['domain'], adj[0]['domain'])} roles — strengthen the proof first."
        else:
            main = "Your CV doesn't match a clear role family yet — here's what to strengthen."

        # "Your CV is missing" — display-ready skill gaps aggregated from the
        # roles the CV is closest to. Domain-agnostic: never lists a skill the
        # CV already has (per-role `missing` already excludes the CV's skills).
        cv_skills = set(profile["skills"])
        freq = {}
        for r in best + adj:
            for s in r["missing"]:
                if s == "leadership":              # too vague to show as a gap
                    continue
                if s in cv_skills:                 # safety: never flag a present skill
                    continue
                freq[s] = freq.get(s, 0) + 1
        toks = sorted(freq, key=lambda s: (1 if s in CV_HARD_GAPS else 0, freq[s]), reverse=True)[:6]
        if profile["weak_swedish"] and any(r["language_sensitive"] for r in best + adj):
            toks = toks[:5] + ["swedish working proficiency"]
        missing = [pretty(s) for s in toks]

        # CV improvements (domain-agnostic).
        t = (cv_text or "").lower()
        result_words = any(w in t for w in ("increase", "reduc", "grew", "growth", "%", "kpi",
                                            "result", "saved", "boosted", "improv", "ökade", "minskade"))
        improvements = []
        if not result_words:
            improvements.append("Add measurable impact — numbers, %, and what changed because of your work.")
        if len(profile["skills"]) < 5:
            improvements.append("Add a clear skills section that lists your tools.")
        if not profile["languages"]:
            improvements.append("State your Swedish and English level explicitly.")
        if is_senior and best:
            improvements.append("Frame senior scope explicitly — ownership, scale, and the impact you led.")
        if not improvements:
            improvements.append("Strong structure — focus on closing the missing skills above.")

        # Keywords.
        seen, keywords = set(), []
        for r in best + adj:
            for k in r["keywords"]:
                if k.lower() not in seen:
                    seen.add(k.lower())
                    keywords.append(k)

        # 7-day action plan (domain-agnostic). Apply count = the number of roles
        # that actually fit (precision over volume), not an inflated target.
        plan = []
        best_titles = [r["title"] for r in best[:2]]
        apply_n = len(best) or len(adj)
        if apply_n:
            plan.append(f"Apply to the {apply_n} best-fit role" + ("s" if apply_n != 1 else "")
                        + " this week" + (f" — e.g. {', '.join(best_titles)}." if best_titles else "."))
        if missing:
            plan.append(f"Build proof for {' and '.join(missing[:2])} — a focused project or short course.")
        plan.append("Rewrite your CV: add measurable impact and a clear skills section.")
        if keywords:
            plan.append("Search Platsbanken for " + ", ".join(f'"{k}"' for k in keywords[:4]) + ".")

        sig_field = best[0]["field_id"] if best else (adj[0]["field_id"] if adj else None)
        market_signal = self._market_signal(sig_field, region) if sig_field else None
        why = why_recommendation(profile, domain_name, best, adj, market_signal, region)

        # Grounded LLM narrative: the model rewrites the verdict + "why" using ONLY
        # the deterministic facts above. Falls back to the deterministic text if
        # the LLM is disabled, unavailable, or returns something invalid. The
        # per-request backend label reflects what actually wrote the narrative.
        backend_label = self.retrieval_backend
        if self.llm and self.llm.ok and (best or adj):
            regional_outlook = self._regional_outlook(pdomain, sig_field, region)
            gen = self.llm.generate({
                "headline_mode": "deterministic",
                "domain": domain_name,
                "seniority": profile["seniority"],
                "cv_skills": [pretty(s) for s in profile["skills"][:6]],
                "best_fit_roles": [r["title"] for r in best[:5]],
                "adjacent_roles": [r["title"] for r in adj[:3]],
                "off_lane_roles": [r["title"] for r in avoid[:3]],
                "missing_skills": missing[:4],
                "market_signal": market_signal,
                "region": region,
                "regional_outlook": regional_outlook,
            })
            if gen:
                why = gen["why_recommendation"]
                if market_signal and len(why) >= 2:
                    why[1] = (
                        "Public job-ad signals show "
                        + market_signal.replace(" · ", ", ").lower()
                        + "."
                    )
                main = self._decision_headline(profile, best, adj, market_signal)
                backend_label = "llm:" + self.llm.model_id
            else:
                raise RuntimeError("LLM generation failed")

        return {
            "main_answer": main,
            "why_recommendation": why,
            "primary_domain": pdomain,
            "domain_label": self.domain_label.get(pdomain, pdomain),
            "best_fit_roles": [r["title"] for r in best],
            "adjacent_roles": [r["title"] for r in adj],
            "not_your_main_lane_roles": [r["title"] for r in avoid],
            "missing_skills": missing,
            "cv_improvements": improvements,
            "search_keywords": keywords[:7],
            "action_plan_7_day": plan,
            "market_signal": market_signal,
            "backend": backend_label,
            "extracted": {
                "seniority": profile["seniority"],
                "domain": pdomain,
                "tools": [pretty(s) for s in profile["skills"][:8]],
                "languages": profile["languages"],
            },
        }


_engine = None
_engine_lock = threading.Lock()


def get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = _Engine()
    return _engine


def analyze_cv(cv_text, region=None, swedish_level=None, target_role=None):
    return get_engine().analyze(cv_text, region=region, swedish_level=swedish_level, target_role=target_role)
