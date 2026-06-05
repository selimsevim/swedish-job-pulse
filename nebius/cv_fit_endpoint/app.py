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
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

# Work whether launched as `uvicorn app:app` (from this folder) or
# `uvicorn nebius.cv_fit_endpoint.app:app` (from the repo root): ensure this
# folder is importable so `cv_fit_core` resolves either way.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv_fit_core  # noqa: E402

app = FastAPI(title="Swedish Job Pulse — CV Fit", version="1.0.0")


class CvFitRequest(BaseModel):
    cv_text: str
    region: Optional[str] = None
    swedish_level: Optional[str] = None     # native | good | basic | none
    target_role: Optional[str] = None


@app.get("/health")
def health():
    eng = cv_fit_core.get_engine()
    return {"status": "ok", "backend": eng.backend, "roles": len(eng.catalog)}


@app.post("/cv-fit")
def cv_fit(req: CvFitRequest):
    # The CV text is used only to compute the report and is not persisted.
    return cv_fit_core.analyze_cv(
        req.cv_text, region=req.region,
        swedish_level=req.swedish_level, target_role=req.target_role,
    )
