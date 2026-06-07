# Nebius Serverless AI Readiness

Swedish Job Pulse is static-first, but the data and ML layer is designed to run as Nebius Serverless AI Jobs.

Official context:

- [Nebius Serverless AI overview](https://docs.nebius.com/serverless/overview)
- [Nebius Serverless AI jobs quickstart](https://docs.nebius.com/serverless/quickstart/jobs)

Nebius Serverless AI supports containerized workloads as Jobs for finite background work and Endpoints for interactive inference. This project uses that shape directly:

```text
Public JobTech data
  -> Job 1: feature generation
  -> Job 2: ML training and evaluation
  -> Job 3: batch scoring and JSON artifacts
  -> Job 4: CV role-skill index + synthetic-CV evaluation
  -> Static website  (PDF or pasted CV text parsed in-browser; nothing uploaded)
  -> Optional Endpoint: /cv-fit
```

No credentials are hardcoded here. Nebius authentication, registry credentials, or object-storage credentials must be provided at runtime through the Nebius platform, CLI profile, or secret store.

## Verified deployment

Run on Nebius Serverless AI from a public GHCR image (linux/amd64). The AI/ML
path is a **grounded-LLM `/cv-fit` endpoint**: deterministic TF-IDF retrieval
produces the facts; a self-hosted **Qwen2.5-7B-Instruct** writes the narrative,
constrained to those facts. A CPU TF-IDF endpoint is the reproducible fallback.

- **Serverless AI Job** `swedish-job-pulse-rebuild` (`cpu-d3` / `4vcpu-16gb`,
  image `ghcr.io/selimsevim/swedish-job-pulse:latest`) — `./scripts/rebuild_career_reality.sh`
  ran end-to-end and reached **COMPLETED**. Logs: **7/7 JSON artifacts validated**;
  CV primary-domain accuracy 1.0; CV no-collapse 1.0.
- **Grounded-LLM Endpoint** `swedish-job-pulse-cv-fit-llm`
  (**GPU `gpu-l40s-d` / `1gpu-16vcpu-96gb`, 1× NVIDIA L40S**, image
  `ghcr.io/selimsevim/cv-fit-endpoint:llm`) — **RUNNING**, token-protected.
  `GET /health` ->
  `{"status":"ok","backend":"llm:Qwen/Qwen2.5-7B-Instruct","retrieval":"tfidf-fallback","roles":41,"llm":{"model":"Qwen/Qwen2.5-7B-Instruct","ok":true,"device":"cuda"}}`;
  unauthenticated `POST /cv-fit` -> 401; warm latency **~1.7 s / request**. The
  **same senior SFMC CV in different regions yields genuinely different,
  data-grounded advice** (cross-region demand ranked by real ad volume):
  *Stockholms län* -> "the strongest local market with 1278 ads"; *Norrbottens /
  Gotlands län* (thin) -> "few ads here — search Stockholm / Västra Götaland, or
  go remote". The GPU endpoint bills while running and is deleted after the proof.
- **CPU TF-IDF endpoint** `swedish-job-pulse-cv-fit` (`cpu-d3` / `4vcpu-16gb`,
  image `ghcr.io/selimsevim/cv-fit-endpoint:latest`) — **RUNNING**,
  token-protected. `GET /health` -> `{"status":"ok","backend":"tfidf-fallback","roles":41}`;
  unauthenticated -> 401. The always-on, reproducible fallback.

**Why grounded generation, and how it stays honest.** Retrieval (which roles
match) is deterministic and reproducible; the LLM only turns that evidence into
language, using greedy decoding and constrained to the role titles it is given —
so no hallucinated roles or numbers. Sales/marketing isn't broken out per region
in the public ad data, so for martech CVs the regional view reads the closest
tracked field (**Data/IT**) as a **disclosed proxy** rather than fabricating
figures. An earlier BGE-M3 embedding endpoint was also exercised on the L40S but
retired: swapping TF-IDF cosine for neural cosine barely changed the report (the
rerank dominates), so it did not justify the GPU — the **LLM** is where the GPU
adds real value.

The trend model is used for direction, not exact vacancy-count prediction
(baseline persistence has lower count MAE). Both endpoints are token-protected
and CV text is processed per request, never stored or logged.

Resource IDs, public URLs/IPs, tokens, full logs and responses are kept out of
git (they contain account/project data).

## Local Rebuild

The local command for Jobs 2 and 3 is:

```bash
./scripts/rebuild_career_reality.sh
```

It writes and validates:

- `data/occupation_forecast.json`
- `data/model_metrics.json`
- `data/career_reality.json`
- `data/opportunity_scores.json`
- `data/cv_match_index.json`
- `data/sample_cvs.json`
- `data/cv_match_metrics.json`

## Job 1 - Public Data Processing / Feature Generation

Purpose:

Refresh public labour-market input files.

Commands:

```bash
python3 scripts/collect.py
python3 scripts/process_skill_velocity.py
python3 scripts/process_demand_gap.py
python3 scripts/process_regional_split.py
```

Optional archive processors:

```bash
python3 scripts/process_decay.py
python3 scripts/process_ad_lifespan.py
```

Inputs:

- Public Arbetsformedlingen / JobTech APIs and archive files
- No API key required for the current public endpoints

Outputs:

- `data/live.json`
- `data/history.json`
- `data/meta.json`
- `data/skill_velocity.json`
- `data/demand_gap.json`
- `data/regional_split.json`
- Optional: `data/occupation_decay.json`, `data/ad_lifespan.json`

Runtime:

- CPU-only
- Usually seconds to a few minutes for live API processors
- Archive processors can take longer because they download and scan public historical files

Proof to capture:

- Job log showing each processor command
- Artifact listing or commit diff showing updated `data/*.json`
- No secrets or private URLs visible in logs

## Job 2 - ML Training And Evaluation

Purpose:

Train the 4-week occupation demand trend model and write evaluation metrics.

Command:

```bash
python3 scripts/train_career_signal_model.py
```

Inputs:

- `data/history.json`
- `data/live.json`
- `data/demand_gap.json`

Outputs:

- `data/occupation_forecast.json`
- `data/model_metrics.json`

Model:

- `HistGradientBoostingRegressor`
- Temporal holdout using newest target weeks
- Fixed random state
- Pure-stdlib baseline fallback if scikit-learn is unavailable

Current metrics:

- ML MAE: `90.73`
- Baseline MAE: `80.90`
- ML trend accuracy: `0.607`
- Baseline trend accuracy: `0.227`
- ML macro-F1: `0.477`
- Baseline macro-F1: `0.123`

Important interpretation:

The ML model is not used as an exact vacancy-count predictor. Its value is in trend-direction classification, where it outperforms the baseline. The product uses the forecast direction as an advisory signal, while exact counts remain descriptive.

Runtime:

- CPU-only
- Current dataset is small enough for a low-resource container
- Expected runtime: under a few minutes including dependency import and training
- GPU is unnecessary; if the Nebius preview UI requires a GPU preset, choose the smallest available preset and note that GPU utilization is expected to be near zero

Proof to capture:

- Job log showing `model source : ml`
- Job log showing ML and baseline metrics
- `data/model_metrics.json`
- `data/occupation_forecast.json`

## Job 3 - Batch Scoring And JSON Artifact Generation

Purpose:

Combine forecast direction with deterministic career signals and produce UI-ready data.

Command:

```bash
python3 scripts/process_career_reality.py
```

Inputs:

- `data/live.json`
- `data/history.json`
- `data/demand_gap.json`
- `data/skill_velocity.json`
- `data/regional_split.json`
- `data/occupation_forecast.json`

Outputs:

- `data/career_reality.json`
- `data/opportunity_scores.json`

Runtime:

- CPU-only
- Standard library only
- Expected runtime: seconds

Proof to capture:

- Job log showing occupation, skill, region, and career-path counts
- Artifact listing with the two output files
- Website screenshot using the generated artifacts

## Job 4 - CV Role-Skill Index + Synthetic-CV Evaluation

Purpose:

Build the role-skill index that powers the CV Job Fit Scanner, and evaluate the
matcher on synthetic, fictional CVs. No real or personal data is used.

Command:

```bash
python3 scripts/build_cv_match_index.py
```

Inputs:

- curated role catalog + skill vocabulary (in the script)
- synthetic CV profiles (in the script)

Outputs:

- `data/cv_match_index.json` - roles, skills, seniority, language fit
- `data/sample_cvs.json` - synthetic CVs for the in-browser demo
- `data/cv_match_metrics.json` - primary-domain accuracy and no-collapse metrics

Notes:

- The browser does the CV PDF extraction and matching locally; this job only
  builds the shared index and proves matcher quality on synthetic CVs.
- A future embedding model (semantic role/skill matching) plugs in at
  `score_role()` without changing the artifact contract; no fine-tuning needed.

Runtime:

- CPU-only, standard library only, seconds.

### On synonyms / abbreviations (SFMC == Salesforce Marketing Cloud)

The static build uses a small hand-written synonym list to collapse surface
forms before TF-IDF. That list is a **bootstrap and does not scale** — it cannot
enumerate every abbreviation. Two scalable replacements, neither of which uses
runtime online search (which would break reproducibility and static-first):

1. **Neural embeddings (the real fix).** A multilingual embedding model
   (BGE-M3 / Qwen3-Embedding) at the `/cv-fit` endpoint places "SFMC" and
   "Salesforce Marketing Cloud" close together with **no synonym list at all** —
   abbreviation handling is learned, not enumerated. Same cosine contract as the
   TF-IDF path, so the static and endpoint versions stay interchangeable.
2. **Offline LLM alias expansion (optional Job).** An LLM (Qwen / Mistral-class
   instruct) run as a batch job can auto-generate alias clusters from the role /
   skill vocabulary and write them back as data. The static fallback then
   consumes a *generated* synonym map instead of a hand-typed one — scalable and
   still fully reproducible (the generation is the job; its output is committed).

No LLM is required in the current repo. If an optional alias-expansion job is
added later, it should only normalize alias clusters; retrieval and ranking
still own the role matching.

## One Combined Serverless Job

For a simple challenge proof, Jobs 2, 3 and 4 can run as one finite Serverless AI Job:

```bash
./scripts/rebuild_career_reality.sh
```

Example placeholder command shape:

```bash
nebius ai create \
  --type job \
  --name swedish-job-pulse-rebuild \
  --image <public-container-image> \
  --container-command bash \
  --args "-lc './scripts/rebuild_career_reality.sh'" \
  --timeout 30m
```

Use real project, region, platform, preset, subnet, and registry values from your Nebius account. Do not commit those values if they reveal private infrastructure.

## Docker Image

This repo includes a Dockerfile that installs dependencies, rebuilds the ML/data artifacts, and serves the static site.

```bash
docker build -t swedish-job-pulse .
docker run --rm -p 8000:8000 swedish-job-pulse
```

For Nebius, publish the image to a public or Nebius-accessible registry, then reference that image in the Serverless AI Job.

## Optional Endpoint - `/cv-fit`

This endpoint is **implemented** (FastAPI) in
[`nebius/cv_fit_endpoint/`](cv_fit_endpoint/) — see its README to run it.

- **Static baseline:** reproducible **TF-IDF vector retrieval** (synonym-expanded)
  in the browser. No server required.
- **Nebius endpoint:** **neural embedding retrieval with BGE-M3** (or a Qwen3
  embedding model) when `CV_FIT_EMBEDDING_MODEL` is set; otherwise the endpoint
  falls back to the same TF-IDF retrieval so it always runs.
- **Same contract:** `vectorize → cosine similarity → rerank → report`. The
  endpoint reuses the exact ontology + matcher from
  `scripts/build_cv_match_index.py`, so it can never drift from the static site.

### Neural backend (BGE-M3) — build & deploy

The neural path is a **second, separate image**, so the stable TF-IDF endpoint is
never touched:

- `nebius/cv_fit_endpoint/requirements-neural.txt` — torch / transformers /
  sentence-transformers.
- `nebius/cv_fit_endpoint/Dockerfile.neural` — built on the official PyTorch CUDA
  runtime so a Nebius GPU (L40S / H100) is used out of the box.
- `scripts/build_neural_role_index.py` — precomputes BGE-M3 embeddings for the 41
  roles into `nebius/cv_fit_endpoint/neural_role_index.json` (1024-dim), baked
  into the image so the endpoint does **not** re-embed roles on cold start.
- `scripts/evaluate_neural_cv_fit.py` — benchmarks TF-IDF vs BGE-M3 on the
  synthetic CVs and writes `data/neural_cv_match_metrics.json`.

`cv_fit_core.py` is env-gated by `CV_FIT_EMBEDDING_MODEL`: set to `BAAI/bge-m3` it
loads the model + precomputed index and serves `backend: neural`; if the model
fails to load it reports `backend: error` (it does **not** silently pretend to be
neural). Unset, it stays on the reproducible TF-IDF fallback.

Why the endpoint is the high-quality path: a multilingual embedding model places
"SFMC" and "Salesforce Marketing Cloud" close together with **no synonym list at
all** — abbreviation/paraphrase equivalence is learned, not enumerated — which is
exactly the limitation of the static bootstrap synonym list.

```text
POST /cv-fit
{ "cv_text": "… raw CV text …", "region": "Stockholms län",
  "swedish_level": "basic", "target_role": "Solution Architect" }
->
{ "main_answer": "Your CV is strongest for CRM / marketing automation roles.",
  "best_fit_roles": ["Salesforce Marketing Cloud Consultant", "Martech Consultant", …],
  "adjacent_roles": [...], "not_your_main_lane_roles": ["SEO Specialist", …],
  "missing_skills": [...], "cv_improvements": [...], "search_keywords": [...],
  "action_plan_7_day": [...], "market_signal": "Rising demand · high crowding · …" }
```

**Uploaded CVs are processed at request time and not stored or logged.** No
secrets or credentials. The model needs no fine-tuning.

## Hardware And Cost Notes

- CPU is enough for all current scripts.
- The dataset is small: the core challenge artifacts are lightweight JSON files in the current repo.
- No persistent server is required after artifacts are generated.
- Serverless Jobs are a good fit because the workload starts, writes artifacts, and exits.
- Endpoint costs should be avoided unless live per-request scoring is actually needed.

## Submission Proof Checklist

Capture:

- Serverless Job configuration showing the public container image
- Job logs for rebuild command and metrics
- Generated artifact listing or commit diff
- Static website screenshot after artifact generation
- `/cv-fit` `/health` and request/response screenshots if using the endpoint path

Do not capture:

- API tokens
- Nebius credentials
- Private registry credentials
- Personal user data
- Private project IDs if you do not want them public
