"""Optional FastAPI `/cv-fit` endpoint for the CV-to-Market Fit engine.

This endpoint is NOT required by the static website — the site works entirely
from generated JSON with in-browser matching. This is the high-quality,
Nebius-runnable path: it uses a neural multilingual embedding model (BGE-M3 /
Qwen3) when configured, and falls back to the same reproducible TF-IDF retrieval
as the static site otherwise.

Run locally:
    pip install -r requirements-endpoint.txt
    uvicorn app:app --host 0.0.0.0 --port 8080

Enable neural embeddings (downloads the model on first run):
    CV_FIT_EMBEDDING_MODEL=BAAI/bge-m3 uvicorn app:app --port 8080

Privacy: CV text is processed per request in-memory and is never stored or
logged. No secrets or credentials are read from this code.
"""

import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Work whether launched as `uvicorn app:app` (from this folder) or
# `uvicorn nebius.cv_fit_endpoint.app:app` (from the repo root): ensure this
# folder is importable so `cv_fit_core` resolves either way.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv_fit_core  # noqa: E402
import cv_fit_llm  # noqa: E402


@asynccontextmanager
async def lifespan(_app):
    # Load the engine exactly once before health probes can arrive concurrently.
    cv_fit_core.get_engine()
    yield


app = FastAPI(
    title="Swedish Job Pulse — CV Fit",
    version="1.0.0",
    lifespan=lifespan,
)


class CvFitRequest(BaseModel):
    cv_text: str
    region: Optional[str] = None
    swedish_level: Optional[str] = None     # native | good | basic | none
    target_role: Optional[str] = None


@app.get("/health")
def health():
    eng = cv_fit_core.get_engine()
    llm_required = cv_fit_llm.llm_enabled()
    llm_ready = bool(eng.llm and eng.llm.ok)
    out = {
        "status": "ok" if eng.backend_kind != "error" and (not llm_required or llm_ready) else "error",
        "backend": eng.backend,               # human label: llm:<model> | neural:<model> | tfidf-fallback
        "retrieval": eng.retrieval_backend,    # tfidf | neural:<model>
        "roles": len(eng.catalog),
    }
    out["data"] = {                            # freshness of the loaded datasets
        "index_updated": eng.index.get("last_updated"),
        "field_skills_years": eng.field_skills.get("years"),
        "refreshed_from_url": eng.data_refreshed,   # files pulled at boot (CV_FIT_DATA_URL)
    }
    if eng.model_name:
        out["embedding_model"] = eng.model_name   # e.g. BAAI/bge-m3
    if eng.embedding_dim:
        out["embedding_dim"] = eng.embedding_dim
    if eng.llm:                                # grounded LLM generation layer
        out["llm"] = {"model": eng.llm.model_id, "ok": eng.llm.ok, "device": eng.llm.device}
        if eng.llm.error:
            out["llm"]["error"] = eng.llm.error
    if eng.neural_error:
        out["error"] = eng.neural_error
    return out


@app.post("/cv-fit")
def cv_fit(req: CvFitRequest):
    # The CV text is used only to compute the report and is not persisted.
    eng = cv_fit_core.get_engine()
    if cv_fit_llm.llm_enabled() and not (eng.llm and eng.llm.ok):
        raise HTTPException(status_code=503, detail="LLM backend unavailable")
    try:
        return eng.analyze(
            req.cv_text, region=req.region,
            swedish_level=req.swedish_level, target_role=req.target_role,
        )
    except RuntimeError as exc:
        if str(exc) == "LLM generation failed":
            raise HTTPException(status_code=503, detail="LLM generation failed") from exc
        raise
