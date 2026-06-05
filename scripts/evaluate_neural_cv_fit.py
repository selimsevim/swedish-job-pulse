#!/usr/bin/env python3
"""Benchmark TF-IDF vs BGE-M3 (neural) retrieval on the synthetic CVs.

Same rerank for both backends (semantic + skill overlap + seniority + domain
guardrails); only the SEMANTIC similarity differs (TF-IDF cosine vs neural
embedding cosine). Reports, per backend:
  - primary-domain accuracy
  - no-collapse rate
  - top-3 expected-domain hit
  - wrong-domain rate
  - average latency (ms)

Output: data/neural_cv_match_metrics.json

Run (needs torch + sentence-transformers; runs natively on CPU/GPU/MPS):
    python3 scripts/evaluate_neural_cv_fit.py --model BAAI/bge-m3
"""

import argparse
import datetime as dt
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")
sys.path.insert(0, HERE)

import build_cv_match_index as bm  # noqa: E402


def role_text(role):
    parts = [role["title"]] + role.get("aliases", []) + role.get("terms", []) \
        + role.get("required_skills", []) + role.get("nice_skills", [])
    return " ".join(parts)


def rank(profile, roles, sem_by_role):
    """Mirror of cv_fit_core._Engine._rank (same weights)."""
    cv_skills = set(profile["skills"])
    scored = []
    for r in roles:
        s = sem_by_role.get(r["role_id"], 0.0)
        req = r["required_skills"]
        cov = (sum(1 for x in req if x in cv_skills) / len(req)) if req else 0.0
        gap = bm.SEN_ORDER[r["seniority"]] - bm.SEN_ORDER.get(profile["seniority"], 0)
        sen_pen = 0.12 * gap if gap > 0 else 0.0
        lang_pen = 0.12 if (r["language_sensitive"] and profile["weak_swedish"]) else 0.0
        fit = max(0.0, 0.55 * s + 0.30 * cov - sen_pen - lang_pen)
        scored.append({
            "role_id": r["role_id"], "title": r["title"], "domain": r["domain"],
            "field_id": r["field_id"], "field_label": r["field_label"],
            "seniority": r["seniority"], "semantic": s, "coverage": cov, "gap": gap,
            "fit": fit, "missing": [x for x in req if x not in cv_skills],
            "language_sensitive": r["language_sensitive"], "keywords": r["search_keywords"],
        })
    scored.sort(key=lambda x: x["fit"], reverse=True)
    return scored


def evaluate(name, sem_fn, roles):
    rows, dom_hits, collapse_ok, top3_hits, lat = [], 0, 0, 0, []
    for cv in bm.SYNTHETIC_CVS:
        prof = bm.extract_cv(cv["text"])
        t0 = time.perf_counter()
        sem = sem_fn(cv["text"])
        scored = rank(prof, roles, sem)
        pdomain, best, adj, avoid = bm.bucket(prof, scored)
        lat.append((time.perf_counter() - t0) * 1000.0)

        dom_ok = pdomain == cv["expect_domain"]
        top_ids = {s["role_id"] for s in (best + adj)[:5]}
        no_collapse = not (cv.get("must_not_top", set()) & top_ids)
        top3 = any(s["domain"] == cv["expect_domain"] for s in (best + adj)[:3])
        dom_hits += int(dom_ok); collapse_ok += int(no_collapse); top3_hits += int(top3)
        rows.append({"cv": cv["name"], "primary_domain": pdomain,
                     "expected_domain": cv["expect_domain"], "domain_hit": dom_ok,
                     "no_collapse": no_collapse, "top3_domain_hit": top3,
                     "best": [s["title"] for s in best[:3]]})
    n = len(bm.SYNTHETIC_CVS) or 1
    return {
        "backend": name, "n_cvs": n,
        "primary_domain_accuracy": round(dom_hits / n, 3),
        "no_collapse_rate": round(collapse_ok / n, 3),
        "top3_expected_domain_hit": round(top3_hits / n, 3),
        "wrong_domain_rate": round((n - dom_hits) / n, 3),
        "avg_latency_ms": round(sum(lat) / len(lat), 1),
        "per_cv": rows,
    }


def main():
    ap = argparse.ArgumentParser(description="Benchmark TF-IDF vs neural CV fit")
    ap.add_argument("--model", default=os.environ.get("CV_FIT_EMBEDDING_MODEL", "BAAI/bge-m3"))
    ap.add_argument("--index", default=os.path.join(DATA_DIR, "cv_match_index.json"))
    ap.add_argument("--out", default=os.path.join(DATA_DIR, "neural_cv_match_metrics.json"))
    args = ap.parse_args()

    index = json.load(open(args.index, encoding="utf-8"))
    roles = index["roles"]
    idf = index.get("idf", {})
    tfidf_vectors = {r["role_id"]: r.get("vector", {}) for r in roles}

    def sem_tfidf(text):
        q = bm.embed_query(text, idf)
        return {r["role_id"]: bm.cosine(q, tfidf_vectors[r["role_id"]]) for r in roles}

    import numpy as np
    from sentence_transformers import SentenceTransformer
    print(f"Loading {args.model} ...")
    model = SentenceTransformer(args.model)
    role_vecs = model.encode([role_text(r) for r in roles], normalize_embeddings=True)
    role_index = {roles[i]["role_id"]: np.asarray(role_vecs[i]) for i in range(len(roles))}

    def sem_neural(text):
        qv = np.asarray(model.encode([text], normalize_embeddings=True)[0])
        return {rid: float(np.dot(qv, ev)) for rid, ev in role_index.items()}

    tfidf = evaluate("tfidf", sem_tfidf, roles)
    neural = evaluate("neural:" + args.model, sem_neural, roles)

    doc = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": args.model,
        "embedding_dim": int(role_vecs.shape[1]),
        "note": ("Both backends share the same rerank; only the semantic score "
                 "differs. 'better' should only be claimed where these numbers support it."),
        "tfidf": tfidf,
        "neural": neural,
    }
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, args.out)

    def line(b):
        return (f"  {b['backend'][:22]:22} domain={b['primary_domain_accuracy']} "
                f"no_collapse={b['no_collapse_rate']} top3={b['top3_expected_domain_hit']} "
                f"wrong={b['wrong_domain_rate']} latency={b['avg_latency_ms']}ms")
    print(line(tfidf)); print(line(neural))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
