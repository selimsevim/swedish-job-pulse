"""Grounded LLM narrative for the /cv-fit endpoint (the Nebius GPU path).

Division of labour:
  * Retrieval + ranking (cv_fit_core) stays DETERMINISTIC and produces the FACTS:
    matched role titles, skill gaps, the market signal, the region.
  * This module asks a self-hosted instruct LLM (served on the Nebius Serverless
    AI GPU endpoint) to WRITE the verdict + "why" + search strategy, strictly
    grounded in those facts — it may only use the role titles it is given, and
    must not invent roles, employers, or statistics.

So the LLM reasons and explains; it never decides which roles match. That keeps
the endpoint reproducible (the facts are deterministic; decoding is greedy) and
honest (no hallucinated roles or numbers).

Environment
  CV_FIT_LLM_MODEL          HF id of an instruct model, e.g.
                            Qwen/Qwen2.5-7B-Instruct. UNSET -> LLM disabled and
                            the caller uses the deterministic report.
  CV_FIT_LLM_MAX_NEW_TOKENS default 320
  CV_FIT_LLM_DEVICE         auto | cuda | mps | cpu (default auto)

Privacy: CV-derived facts are processed in-memory per request; nothing is stored
or logged. No secrets are read here.
"""

from __future__ import annotations

import json
import os
import re
import threading

MODEL_ID = os.environ.get("CV_FIT_LLM_MODEL", "").strip()
MAX_NEW_TOKENS = int(os.environ.get("CV_FIT_LLM_MAX_NEW_TOKENS", "700"))
DEVICE_PREF = os.environ.get("CV_FIT_LLM_DEVICE", "auto").strip().lower()

_SYSTEM = (
    "You are a data-literate Swedish job-market consultant — not a form. You are given FACTS "
    "produced by a deterministic matcher over public Arbetsförmedlingen / JobTech job-ad data. "
    "Advise honestly and specifically using ONLY these facts.\n"
    "Rules:\n"
    "- Use only the exact role titles provided. Never invent roles, employers, skills, or numbers.\n"
    "- Public job-ad signals are demand signals, not the whole labour market — never claim they cover all jobs.\n"
    "- The headline must make a DECISION, not repeat the user's filters:\n"
    "    * Name one or two exact titles from best_fit_roles.\n"
    "    * State the most important tradeoff from market_signal or missing_skills.\n"
    "    * Never mention the selected region, local market, or remote work in the headline. Put all "
    "regional advice in why_recommendation item 3 instead.\n"
    "    * Preserve the exact strength of market_signal: high crowding must not become moderate or low.\n"
    "    * Never begin with 'Search in' and never say only 'focus on <domain> roles'.\n"
    "- Reason about region from regional_outlook, like a consultant. Use selected_region.local_market:\n"
    "    * 'thin'  -> SAY this region has few such roles (cite its rank/ads) and advise EITHER remote work OR "
    "moving the search to the strongest regions in top_regions (name 1-2, e.g. the top by 'ads').\n"
    "    * 'moderate' -> note it's a mid-sized market; mention remote and the top region as options.\n"
    "    * 'strong' -> say it's one of the strongest local markets and to focus the search there.\n"
    "    * If data_basis is 'proxy', disclose this field isn't tracked per region so you use the proxy_field "
    "market (e.g. 'the wider tech market') as the regional indicator.\n"
    "    * If data_basis is 'national_only' (or regional_outlook is null), say there's no regional breakdown for "
    "this field and advise a national + remote search. Do NOT name regions then.\n"
    "- Be concrete and concise. No hype, no filler.\n"
    "Output ONE single JSON object and NOTHING else (no prose before or after, no second "
    "object). It MUST contain BOTH keys. 'main_answer' is ONE sentence. "
    "'main_answer' must include an exact best-fit role title and a useful tradeoff. "
    "'why_recommendation' is an array of EXACTLY 3 short sentences (max ~28 words each): "
    "(1) the CV evidence and best-fit titles, (2) the market signal, (3) the regional strategy per the rules above. "
    "Keep the whole response under 130 words. Schema:\n"
    '{"main_answer": "<one sentence>", "why_recommendation": ["<sentence 1>", "<sentence 2>", "<sentence 3>"]}'
)


_EXTRACT_SYSTEM = (
    "You read a CV (often Swedish or English) and extract a structured profile for a job matcher. "
    "Return STRICT JSON only, no prose.\n"
    "- skills: choose EVERY token from SKILL_VOCAB that the CV clearly evidences — including via Swedish "
    "wording, tools, certifications, or paraphrase (e.g. 'ledde ett team' -> leadership; 'byggde "
    "instrumentpaneler' -> dashboards; 'truckkort' -> forklift). Use ONLY exact tokens from SKILL_VOCAB; "
    "never invent a token and never include a skill the CV does not show.\n"
    "- seniority: entry | mid | senior, inferred from years and scope of responsibility.\n"
    "- target_role: the role the candidate says they are seeking (their words), or empty.\n"
    "- swedish_level: native | good | basic | none | unknown.\n"
    'Schema: {"skills": ["<token>", ...], "seniority": "<entry|mid|senior>", '
    '"target_role": "<role or empty>", "swedish_level": "<level>"}'
)


class _LLM:
    def __init__(self):
        self.model_id = MODEL_ID
        self.ok = False
        self.error = None
        self.device = None
        self._tok = None
        self._model = None
        if MODEL_ID:
            self._load()

    def _pick_device(self):
        import torch
        if DEVICE_PREF in ("cuda", "mps", "cpu"):
            return DEVICE_PREF
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _load(self):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            self.device = self._pick_device()
            dtype = torch.float16 if self.device in ("cuda", "mps") else torch.float32
            self._tok = AutoTokenizer.from_pretrained(MODEL_ID)
            self._model = AutoModelForCausalLM.from_pretrained(MODEL_ID, torch_dtype=dtype)
            self._model.to(self.device)
            self._model.eval()
            self.ok = True
            print(f"[cv-fit] LLM backend active: {MODEL_ID} (device={self.device})")
        except Exception as exc:  # pragma: no cover - runtime/model dependent
            self.error = f"{exc.__class__.__name__}: {exc}"
            self.ok = False
            print("[cv-fit] LLM LOAD FAILED: " + self.error)

    def generate(self, evidence):
        """Return {"main_answer": str, "why_recommendation": [str]} or None."""
        if not self.ok:
            return None
        import torch
        user = "FACTS:\n" + json.dumps(evidence, ensure_ascii=False, indent=2)
        messages = [{"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user}]
        for attempt in range(2):
            try:
                inputs = self._tok.apply_chat_template(
                    messages, add_generation_prompt=True, return_tensors="pt").to(self.device)
                with torch.no_grad():
                    out = self._model.generate(
                        inputs, max_new_tokens=MAX_NEW_TOKENS,
                        do_sample=False,  # greedy -> reproducible
                        pad_token_id=(self._tok.pad_token_id or self._tok.eos_token_id),
                    )
                text = self._tok.decode(out[0][inputs.shape[-1]:], skip_special_tokens=True)
            except Exception as exc:  # pragma: no cover
                print("[cv-fit] LLM generate failed: " + f"{exc.__class__.__name__}")
                return None
            result = _parse_and_ground(text, evidence)
            if result is not None:
                return result
            if attempt == 0:
                best = evidence.get("best_fit_roles", [])
                messages.append({"role": "assistant", "content": text})
                messages.append({
                    "role": "user",
                    "content": (
                        "Rewrite the JSON. The headline failed validation. It must name an exact "
                        f"best-fit title ({'; '.join(best[:3])}) and state a market or skill-gap "
                        "tradeoff. Do not begin with 'Search in' or merely repeat the region."
                    ),
                })
        # No CV text here — only the model's own (non-PII) output head, to
        # diagnose parse or usefulness failures from endpoint logs.
        print("[cv-fit] LLM output failed validation; head=" + repr(text[:280]))
        return None

    def extract_profile(self, cv_text, vocab):
        """Read the CV into a structured profile, constrained to the known skill
        vocabulary. Adds recall over keyword matching (Swedish, paraphrase,
        implied skills) and infers seniority + the candidate's target role.
        Returns {"skills":[token], "seniority":?, "target_role":?,
        "swedish_level":?} or None. Skills are validated against vocab by the
        caller, so the model cannot inject unknown tokens."""
        if not self.ok:
            return None
        import torch
        user = ("SKILL_VOCAB (use only these exact tokens): " + ", ".join(vocab)
                + "\n\nCV:\n" + (cv_text or "")[:6000])
        messages = [{"role": "system", "content": _EXTRACT_SYSTEM},
                    {"role": "user", "content": user}]
        try:
            inputs = self._tok.apply_chat_template(
                messages, add_generation_prompt=True, return_tensors="pt").to(self.device)
            with torch.no_grad():
                out = self._model.generate(
                    inputs, max_new_tokens=256, do_sample=False,
                    pad_token_id=(self._tok.pad_token_id or self._tok.eos_token_id))
            text = self._tok.decode(out[0][inputs.shape[-1]:], skip_special_tokens=True)
        except Exception as exc:  # pragma: no cover
            print("[cv-fit] LLM extract failed: " + f"{exc.__class__.__name__}")
            return None
        obj = _extract_json(text)
        if not isinstance(obj, dict):
            return None
        skills = obj.get("skills")
        skills = [s for s in skills if isinstance(s, str)] if isinstance(skills, list) else []
        sen = obj.get("seniority") if obj.get("seniority") in ("entry", "mid", "senior") else None
        tgt = obj.get("target_role")
        tgt = tgt.strip() if isinstance(tgt, str) and tgt.strip() else None
        sw = obj.get("swedish_level") if obj.get("swedish_level") in ("native", "good", "basic", "none") else None
        return {"skills": skills, "seniority": sen, "target_role": tgt, "swedish_level": sw}


def _extract_json(text):
    """Parse the FIRST JSON object in the model output and ignore any trailing
    prose (instruct models often add an explanation after the JSON). Tolerates
    ``` fences. Returns None if the object is malformed/truncated (caller then
    falls back to the truncation-tolerant regex extractor)."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.MULTILINE).strip()
    start = t.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(t[start:])   # stops at end of first object
        return obj
    except Exception:
        return None


def _unescape(s):
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s.replace('\\"', '"').replace("\\n", " ").replace("\\\\", "\\").strip()


def _extract_fields(text):
    """Layout-tolerant field recovery. Instruct models sometimes split the output
    into two fragments — {"main_answer": "..."} then a bare ["...", "..."] array,
    or a second {"why_recommendation": [...]} object — and may truncate or add
    trailing prose. Pull main_answer and the why list wherever they land."""
    if not text:
        return None
    mm = re.search(r'"main_answer"\s*:\s*"((?:\\.|[^"\\])*)"', text)
    main = _unescape(mm.group(1)) if mm else None
    # why list: prefer the keyed array; else the first bracketed list of strings
    # (a bare array the model emitted after the main object).
    span = None
    km = re.search(r'"why_recommendation"\s*:\s*\[', text)
    if km:
        span = text[km.end() - 1:]
    else:
        after = text[mm.end():] if mm else text
        bm = re.search(r'\[\s*"', after)
        if bm:
            span = after[bm.start():]
    why = []
    if span:
        close = span.find("]")
        seg = span[: close + 1] if close != -1 else span      # tolerate truncation
        why = [_unescape(g) for g in re.findall(r'"((?:\\.|[^"\\])*)"', seg)]
    if main or why:
        return {"main_answer": main, "why_recommendation": why}
    return None


def _parse_and_ground(text, evidence):
    obj = _extract_json(text)
    main = obj.get("main_answer") if isinstance(obj, dict) else None
    why = obj.get("why_recommendation") if isinstance(obj, dict) else None
    if isinstance(why, str):
        why = [why]
    # Backfill any missing field from a layout-tolerant scan of the whole text
    # (handles split objects / bare arrays / truncation / trailing prose).
    if not (isinstance(main, str) and main.strip()) or not (isinstance(why, list) and why):
        fx = _extract_fields(text) or {}
        if not (isinstance(main, str) and main.strip()):
            main = fx.get("main_answer")
        if not (isinstance(why, list) and why):
            why = fx.get("why_recommendation")
    if not isinstance(main, str) or not main.strip():
        return None
    if not isinstance(why, list):
        return None
    why = [str(w).strip() for w in why if isinstance(w, (str, int, float)) and str(w).strip()][:3]
    if len(why) != 3:
        return None
    best = [str(role).strip() for role in evidence.get("best_fit_roles", []) if str(role).strip()]
    main_lower = main.lower().strip()
    if evidence.get("headline_mode") != "deterministic":
        if main_lower.startswith("search in "):
            return None
        if best and not any(role.lower() in main_lower for role in best):
            return None
        regional = evidence.get("regional_outlook") or {}
        selected = regional.get("selected_region") or {}
        selected_name = str(selected.get("region") or "").lower()
        if (
            (selected_name and selected_name in main_lower)
            or "local market" in main_lower
            or "remote" in main_lower
        ):
            return None
        market = str(evidence.get("market_signal") or "").lower()
        blob_lower = (main + " " + " ".join(why)).lower()
        if "high crowding" in market:
            if not any(term in main_lower for term in ("high crowding", "high competition", "highly competitive")):
                return None
            if "moderate crowding" in blob_lower or "low crowding" in blob_lower:
                return None
    blob = (main + " " + " ".join(why)).strip()
    if len(blob) < 10:
        return None
    return {"main_answer": main.strip(), "why_recommendation": why}


_llm = None
_llm_lock = threading.Lock()


def get_llm():
    global _llm
    if _llm is None:
        with _llm_lock:
            if _llm is None:
                _llm = _LLM()
    return _llm


def llm_enabled():
    return bool(MODEL_ID)


def status():
    eng = get_llm()
    return {"model": eng.model_id or None, "ok": eng.ok,
            "device": eng.device, "error": eng.error}


def generate_narrative(evidence):
    return get_llm().generate(evidence)
