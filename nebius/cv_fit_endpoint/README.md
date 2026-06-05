# `/cv-fit` endpoint (optional, Nebius-runnable)

The high-quality neural path for the CV-to-Market Fit engine. The static website
does **not** need this — it matches CVs in the browser from generated JSON. This
endpoint exists for live, server-side CV analysis with a real multilingual
embedding model.

**Same contract as the static site:** `vectorize → cosine similarity → rerank →
report`. It reuses the exact role ontology, tokenizer, scoring and bucketing from
[`scripts/build_cv_match_index.py`](../../scripts/build_cv_match_index.py), so the
endpoint and the static site never diverge.

- **Static baseline:** reproducible TF-IDF vector retrieval (synonym-expanded).
- **This endpoint:** neural multilingual embeddings (BGE-M3 / Qwen3) when
  configured; otherwise it transparently falls back to the same TF-IDF retrieval
  so it always runs locally.

**Privacy:** uploaded CV text is processed per request, in memory, and is **never
stored or logged**. No secrets, no credentials in this folder.

## Run locally (TF-IDF fallback — no model download)

```bash
python3 -m pip install -r nebius/cv_fit_endpoint/requirements-endpoint.txt
# from the repo root (folder uses an underscore so the module path is valid):
uvicorn nebius.cv_fit_endpoint.app:app --host 127.0.0.1 --port 8080
# or, equivalently, from inside the folder:
#   cd nebius/cv_fit_endpoint && uvicorn app:app --port 8080
```

Then:

```bash
curl -s -X POST http://127.0.0.1:8080/cv-fit \
  -H 'content-type: application/json' \
  --data @nebius/cv_fit_endpoint/test_payload.json | python3 -m json.tool
```

`GET /health` returns the active backend and role count.

> The folder is named `cv_fit_endpoint` (underscore) on purpose: a hyphenated
> name (`cv-fit-endpoint`) is not a valid Python module path, so
> `uvicorn nebius.cv-fit-endpoint.app:app` would fail to import.

## Enable neural embeddings (BGE-M3 / Qwen3)

Uncomment the neural deps in `requirements-endpoint.txt`, install them, then set
the model env var (downloads the model on first run):

```bash
CV_FIT_EMBEDDING_MODEL=BAAI/bge-m3 uvicorn app:app --port 8080
# or a Qwen3 embedding model, e.g. Qwen/Qwen3-Embedding-0.6B
```

With a model set, role docs and the CV are embedded neurally and ranked by
cosine — abbreviation/paraphrase equivalence (SFMC ≈ Salesforce Marketing Cloud)
is **learned, not enumerated**, so the hand-written synonym list is unnecessary.

## Request / response

`POST /cv-fit`

```json
{
  "cv_text": "… raw CV text …",
  "region": "Stockholms län",          // optional
  "swedish_level": "basic",            // optional: native | good | basic | none
  "target_role": "Solution Architect"  // optional
}
```

Returns the same report structure as the website: `main_answer`,
`best_fit_roles`, `adjacent_roles`, `not_your_main_lane_roles`, `missing_skills`,
`cv_improvements`, `search_keywords`, `action_plan_7_day`, `market_signal`, plus
`backend` and `extracted`. A synthetic request is in
[`test_payload.json`](./test_payload.json); the expected shape (TF-IDF fallback)
is in [`expected_response.json`](./expected_response.json).

## Test (no server, no model, standard library only)

```bash
python3 nebius/cv_fit_endpoint/test_cv_fit.py
```

Runs the core on the synthetic CV and asserts the report is valid and that a
senior SFMC/Martech CV is **not** collapsed into generic roles.

## Docker

```bash
docker build -f nebius/cv_fit_endpoint/Dockerfile -t cv_fit_endpoint .
docker run --rm -p 8080:8080 cv_fit_endpoint
# neural: docker run --rm -e CV_FIT_EMBEDDING_MODEL=BAAI/bge-m3 -p 8080:8080 cv_fit_endpoint
```

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `CV_FIT_EMBEDDING_MODEL` | _(unset → TF-IDF)_ | Neural embedding model id (e.g. `BAAI/bge-m3`) |
| `CV_FIT_INDEX_PATH` | `data/cv_match_index.json` | Role ontology + vectors |
| `CV_FIT_CAREER_PATH` | `data/career_reality.json` | Market signals (optional) |
