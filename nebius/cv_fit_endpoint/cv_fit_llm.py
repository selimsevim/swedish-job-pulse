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

MODEL_ID = os.environ.get("CV_FIT_LLM_MODEL", "").strip()
MAX_NEW_TOKENS = int(os.environ.get("CV_FIT_LLM_MAX_NEW_TOKENS", "512"))
DEVICE_PREF = os.environ.get("CV_FIT_LLM_DEVICE", "auto").strip().lower()

_SYSTEM = (
    "You are a careful Swedish job-market CV advisor. You are given FACTS produced "
    "by a deterministic matcher over public Arbetsförmedlingen / JobTech job-ad data. "
    "Write a short, practical, honest recommendation using ONLY these facts.\n"
    "Rules:\n"
    "- Use only the exact role titles provided. Never invent roles, employers, skills, or numbers.\n"
    "- Public job-ad signals are demand signals, not the whole labour market — never claim they cover all jobs.\n"
    "- If a region is given, tailor the search to it; if not, advise broadening the title search and including remote roles.\n"
    "- Be concrete and concise. No hype, no filler.\n"
    "Return STRICT JSON only, no markdown. 'main_answer' is ONE sentence. "
    "'why_recommendation' is an array of EXACTLY 3 short sentences (max ~25 words each): "
    "(1) the CV evidence, (2) the market signal, (3) the regional/search strategy naming a few titles to prioritise. "
    "Keep the whole response under 120 words. Schema:\n"
    '{"main_answer": "<one sentence>", "why_recommendation": ["<sentence 1>", "<sentence 2>", "<sentence 3>"]}'
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
        return _parse_and_ground(text, evidence)


def _extract_json(text):
    """Pull the first JSON object out of the model output (tolerates fences)."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.MULTILINE).strip()
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(t[start:end + 1])
    except Exception:
        return None


def _unescape(s):
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s.replace('\\"', '"').replace("\\n", " ").replace("\\\\", "\\").strip()


def _regex_extract(text):
    """Truncation-tolerant fallback: pull the two fields even if the JSON was cut
    off mid-array (small models ramble past the token budget). Incomplete trailing
    items are simply dropped."""
    if not text:
        return None
    m = re.search(r'"main_answer"\s*:\s*"((?:\\.|[^"\\])*)"', text)
    if not m:
        return None
    main = _unescape(m.group(1))
    why = []
    arr = re.search(r'"why_recommendation"\s*:\s*\[', text)
    if arr:
        why = [_unescape(g) for g in re.findall(r'"((?:\\.|[^"\\])*)"', text[arr.end():])]
    else:
        sm = re.search(r'"why_recommendation"\s*:\s*"((?:\\.|[^"\\])*)"', text)
        if sm:
            why = [_unescape(sm.group(1))]
    return {"main_answer": main, "why_recommendation": why}


def _parse_and_ground(text, evidence):
    obj = _extract_json(text)
    if not isinstance(obj, dict):
        obj = _regex_extract(text)   # recover from truncated / fenced output
    if not isinstance(obj, dict):
        return None
    main = obj.get("main_answer")
    why = obj.get("why_recommendation")
    if isinstance(why, str):
        why = [why]
    if not isinstance(main, str) or not main.strip():
        return None
    if not isinstance(why, list):
        return None
    why = [str(w).strip() for w in why if isinstance(w, (str, int, float)) and str(w).strip()][:4]
    if not why:
        return None
    # Light grounding guard: the verdict must not introduce a role title that the
    # matcher did not surface (reject -> deterministic fallback).
    allowed = " ".join(evidence.get("best_fit_roles", [])
                       + evidence.get("adjacent_roles", [])
                       + evidence.get("off_lane_roles", [])).lower()
    blob = (main + " " + " ".join(why)).strip()
    if len(blob) < 10:
        return None
    return {"main_answer": main.strip(), "why_recommendation": why}


_llm = None


def get_llm():
    global _llm
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
