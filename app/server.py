"""Public Railway app: serves the static Swedish Job Pulse frontend and
securely proxies CV-fit requests to the Nebius `/cv-fit` endpoint.

    Browser  →  this Railway app  →  Nebius /cv-fit endpoint

The Nebius credentials live ONLY in this server's environment (set as Railway
environment variables) and are never sent to the browser:

    NEBIUS_CV_FIT_URL    base URL of the Nebius endpoint, e.g.
                         https://<endpoint>.nebius.cloud   (NO trailing /cv-fit)
    NEBIUS_CV_FIT_TOKEN  bearer token for the endpoint

Privacy contract (matches the in-browser scanner and the Nebius endpoint):
    * CV text is forwarded to Nebius for the single request only.
    * CV text is NEVER logged and NEVER stored by this server.
    * If the Nebius env vars are missing or the endpoint is unreachable, the
      API returns an explicit error. It never silently substitutes a local
      baseline report.

Start (Railway / local):
    uvicorn app.server:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Repo root holds the static frontend (index.html, app.js, style.css, data/).
ROOT = Path(__file__).resolve().parent.parent

NEBIUS_CV_FIT_URL = (os.environ.get("NEBIUS_CV_FIT_URL") or "").strip().rstrip("/")
NEBIUS_CV_FIT_TOKEN = (os.environ.get("NEBIUS_CV_FIT_TOKEN") or "").strip()
# Neural inference (BGE-M3) can be slower than the local baseline; allow plenty.
REQUEST_TIMEOUT = float(os.environ.get("NEBIUS_CV_FIT_TIMEOUT", "60"))

# Only these fields are ever forwarded upstream (matches the Nebius schema).
_ALLOWED_FIELDS = ("cv_text", "region", "swedish_level", "target_role")


def nebius_configured() -> bool:
    """True only when BOTH the URL and token env vars are present."""
    return bool(NEBIUS_CV_FIT_URL and NEBIUS_CV_FIT_TOKEN)


app = FastAPI(title="Swedish Job Pulse — Public App", version="1.0.0")


@app.get("/api/health")
async def api_health():
    """Verify that the configured upstream is a healthy LLM endpoint."""
    if not nebius_configured():
        return {"status": "ok", "neural_available": False}

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{NEBIUS_CV_FIT_URL}/health",
                headers={"Authorization": f"Bearer {NEBIUS_CV_FIT_TOKEN}"},
            )
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {"status": "ok", "neural_available": False}

    backend = data.get("backend") if isinstance(data, dict) else None
    available = (
        resp.is_success
        and data.get("status") == "ok"
        and isinstance(backend, str)
        and backend.startswith("llm:")
    )
    return {
        "status": "ok",
        "neural_available": available,
        "backend": backend if available else None,
    }


@app.post("/api/cv-fit")
async def api_cv_fit(request: Request):
    """Securely proxy a CV-fit request to the Nebius `/cv-fit` endpoint.

    Never logs or stores the request body (it contains CV text). On any
    misconfiguration or upstream failure, returns an explicit JSON error.
    """
    if not nebius_configured():
        # AI backend not configured.
        return JSONResponse(
            status_code=503,
            content={
                "error": "nebius_unconfigured",
                "detail": "Neural backend is not configured on the server.",
            },
        )

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid_json"})
    if not isinstance(payload, dict):
        return JSONResponse(status_code=400, content={"error": "invalid_json"})

    # Forward ONLY known fields; drop unknowns. Do not log this object.
    body = {k: payload.get(k) for k in _ALLOWED_FIELDS if payload.get(k) is not None}
    if not str(body.get("cv_text", "")).strip():
        return JSONResponse(status_code=400, content={"error": "missing_cv_text"})

    url = f"{NEBIUS_CV_FIT_URL}/cv-fit"
    headers = {
        "Authorization": f"Bearer {NEBIUS_CV_FIT_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError:
        # Network / timeout / DNS failure. No CV text in this log path.
        return JSONResponse(
            status_code=502,
            content={
                "error": "nebius_unreachable",
                "detail": "Could not reach the neural backend.",
            },
        )

    try:
        data = resp.json()
    except ValueError:
        return JSONResponse(
            status_code=502,
            content={"error": "nebius_bad_response"},
        )

    backend = data.get("backend") if isinstance(data, dict) else None
    if resp.is_success and (not isinstance(backend, str) or not backend.startswith("llm:")):
        return JSONResponse(
            status_code=502,
            content={
                "error": "nebius_non_llm_response",
                "detail": "The upstream response was not produced by the LLM.",
            },
        )

    # Pass the upstream status + JSON straight back to the browser.
    return JSONResponse(status_code=resp.status_code, content=data)


# --- Static frontend --------------------------------------------------------
# Explicit, curated routes (no source files, venvs or scripts are exposed).
@app.get("/")
@app.get("/index.html")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/app.js")
def app_js():
    return FileResponse(ROOT / "app.js", media_type="application/javascript")


@app.get("/style.css")
def style_css():
    return FileResponse(ROOT / "style.css", media_type="text/css")


# Generated JSON the frontend loads (career_reality.json, cv_match_index.json,
# sample_cvs.json, …). Read-only static mount.
app.mount("/data", StaticFiles(directory=str(ROOT / "data")), name="data")
