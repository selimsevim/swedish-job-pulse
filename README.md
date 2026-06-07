# Swedish Job Pulse

Swedish Job Pulse is a public-data career guidance website for people in Sweden. It has two ways in:

1. **CV Job Fit Scanner** (primary) &mdash; upload a PDF CV or paste CV text and get a one-page CV-to-market fit report: best-fit roles now, stretch roles, roles to avoid for now, missing skills, CV fixes, search keywords and a 7-day plan.
2. **Career Reality Check** (fallback) &mdash; answer a few questions (target job, region, skills, level) instead of uploading a CV.

It answers one practical question:

> Before you spend weeks applying, is this role realistic for you in the current Swedish labour market &mdash; and if not, what should you apply for and add?

This is not a job board and not a generic AI career coach. It is a static website backed by public Arbetsformedlingen / JobTech labour-market data, an occupation demand trend forecast, a role-skill index, and transparent scoring rules for crowding risk, entry-level access, regional fit, remote signal, and skill momentum.

**Hosting.** The public app is deployed on **Railway** (not GitHub Pages): a small FastAPI server serves the static frontend and securely proxies the optional neural CV analysis to **Nebius**. See [Deploy: Railway + Nebius](#deploy-railway-public-app-host--nebius-ai-backend).

## CV Job Fit Scanner

Upload a PDF CV, or paste CV text, &rarr; get a one-page job-fit report.

**Privacy / reproducibility.** PDFs are parsed **entirely in your browser** with pdf.js. The extracted or pasted CV text is sent through the Railway proxy to Nebius for one request and is not logged or stored. If the LLM is unavailable, no report is produced. No real CV is committed to this repo. The challenge build is demoed and evaluated only on **synthetic, fictional CVs** in [`data/sample_cvs.json`](data/sample_cvs.json).

Three layers:

- **Extraction** &mdash; PDF or pasted CV text is parsed in-browser into `{skills, roles, languages, seniority}`.
- **Retrieval + ranking** &mdash; the profile is vectorized and matched against a role ontology ([`data/cv_match_index.json`](data/cv_match_index.json)), then reranked by skill overlap, seniority, domain fit and Swedish-language fit, enriched with public demand / crowding / regional / trend signals. Retrieval uses a reproducible **multilingual TF-IDF vector space** with synonym/domain expansion (so `SFMC == Salesforce Marketing Cloud == Martech` and a technical martech CV is not flattened into "digital marketing"). The reranker is **domain-agnostic** — no role names or domain special-casing in code.
- **Explanation** &mdash; a self-hosted **Qwen2.5-7B-Instruct** at the Nebius `/cv-fit` endpoint turns that evidence into the verdict, the "Why this recommendation?" lines, and a region-aware search strategy — **grounded** in the retrieved facts (it may only use the role titles it is given) — see [`nebius/README.md`](nebius/README.md).
- **Gap analysis** &mdash; what blocks stronger matches: missing skills, weak proof, language.

**One analysis path.** The scanner calls the Railway proxy (`POST /api/cv-fit`), which forwards to the Nebius grounded-LLM endpoint. If the LLM is unavailable, the UI shows an error and produces no report; it does not silently substitute the local TF-IDF baseline. An optional **Region** selector tailors the market signal and search strategy. The Nebius token is **never** present in `app.js`, `index.html`, or any other file the browser receives — see [Deploy: Railway + Nebius](#deploy-railway-public-app-host--nebius-ai-backend).

The report:

- **Best-fit roles now** / **Stretch roles** / **Roles to avoid for now**
- **Your CV is missing** (priority skill gaps, technical first)
- **Improve your CV by adding** (measurable results, skills section, clearer titles, language level)
- **Search keywords** and a **7-day action plan**

It reflects **public Swedish job-ad data, not the entire hidden job market**, and is not a guarantee of employment. Build the index and run the synthetic-CV evaluation with:

```bash
python3 scripts/build_cv_match_index.py
```

Outputs `data/cv_match_index.json`, `data/sample_cvs.json` and `data/cv_match_metrics.json`. The current metrics are primary-domain accuracy and no-collapse rate on synthetic CVs; they prove the demo matcher stays in the right role family and does not collapse specialist profiles into generic jobs. The matcher in `app.js` mirrors the Python matcher in that script, so the evaluation tests the same pipeline.

## Career Reality Check (fallback)

If you would rather not upload a CV, a collapsed form lets you answer a few questions instead. A user enters:

- Region
- Swedish level
- Current experience area
- Target job
- Skills
- Experience level
- Remote preference
- Study willingness

The site returns one clear consultant answer, in a single vertical flow:

- **Main answer** - a plain-language verdict, e.g. "Don't make developer your main application lane yet" or "Apply now - this target is realistic"
- **Why** - 3-4 short reasons behind the call (no full signal table)
- **Apply for these first** - realistic roles to apply to right now
- **Keep as stretch target** - the target role plus nearby reachable roles (hidden when the target is already realistic)
- **Do this next** - a short action plan (max 4 steps), including search keywords
- **Data signal** - one compact muted line summarising demand direction, crowding, regional fit, and remote signal

The verdict is still computed internally as `Realistic now`, `Reachable in 3-6 months`, `Risky for now`, or `Not enough signal`, but the user sees a single plain-language answer rather than a label plus a data dashboard.

The intended project story is:

```text
Public Swedish job-market data -> serverless ML forecast -> practical career advice website
```

## Why It Exists

People often apply to target roles that are too crowded, too senior, too language-heavy, or weak in their region. Swedish Job Pulse makes those risks visible before someone spends weeks applying in the wrong direction.

It is designed for practical career decisions in Sweden:

- "Can I move from customer service into data analyst work?"
- "Is admin realistic for an entry-level candidate in Skane?"
- "Is truck driving a better first step in Norrbotten than remote office work?"
- "Does nursing demand look strong, and what credential barrier exists?"

## Data Sources

The project uses public Arbetsformedlingen / JobTech data only. No API key is required by the current local pipeline.

- JobSearch API: current active ads, positions, remote share, entry-level share, occupation and region aggregates
- Historical ads and archive-derived files: weekly history, skill momentum, long-range occupation signals
- Search Trends: search attention versus demand, used as a crowding-risk proxy. Search pressure is not the same as applicant count.
- JobTech taxonomy: occupation groups, occupation fields, regions, and skills

No private data, no personal data, and no secrets are used or committed.

## ML Layer

The ML layer is in [`scripts/train_career_signal_model.py`](scripts/train_career_signal_model.py).

It trains a `HistGradientBoostingRegressor` to forecast active-ad demand about 4 weeks ahead per occupation group. The forecast is converted into a direction class:

- `grow`
- `stable`
- `decline`

Features:

- Previous-week active-ad count
- 4-week active-ad average
- 8-week active-ad average
- Relative trend over the last 4 weeks
- Remote share by occupation field
- Entry-level share by occupation field
- Search-attention gap
- Occupation-field code

Evaluation:

- Temporal split: newest target weeks are held out for test
- Current samples: `814`
- Train/test split: `651` train, `163` test
- Forecast horizon: `4` weeks
- Metrics written to [`data/model_metrics.json`](data/model_metrics.json)

### Baseline Comparison

Current metric summary:

| Metric | ML model | Baseline persistence |
|---|---:|---:|
| MAE | `90.73` | `80.90` |
| Trend accuracy | `0.607` | `0.227` |
| Trend macro-F1 | `0.477` | `0.123` |

Important interpretation:

The ML model is **not** used as an exact vacancy-count predictor. Its value is in trend-direction classification, where it outperforms the baseline. The product uses the forecast direction as an advisory signal, while exact counts remain descriptive.

Do not claim that the ML model forecasts vacancy counts better than the baseline. Baseline persistence currently has lower MAE on the count target.

If `scikit-learn` is unavailable, the script still writes valid artifacts using a pure-stdlib moving-average / persistence fallback and flags `model_source: "baseline"`.

## Scoring And Advice Logic

The advice layer is in [`scripts/process_career_reality.py`](scripts/process_career_reality.py).

It combines:

- Occupation demand level
- ML or baseline demand trend
- Crowding risk from demand versus search attention
- Entry-level signal
- Remote signal
- Regional field specialization
- Skill momentum
- Curated career-path templates for common transitions

The regional signal is transparent: the model is national at occupation-group level, and region is applied as a specialization weight from current regional cross-tabs. It is not presented as a true regional time-series forecast.

## Generated Artifacts

The website reads static JSON files from `data/`.

Important generated outputs:

- [`data/occupation_forecast.json`](data/occupation_forecast.json) - per-occupation 4-week forecast and trend class
- [`data/model_metrics.json`](data/model_metrics.json) - model and baseline evaluation
- [`data/career_reality.json`](data/career_reality.json) - full UI model for Career Reality Check
- [`data/opportunity_scores.json`](data/opportunity_scores.json) - compact occupation x region scoring table
- [`data/cv_match_index.json`](data/cv_match_index.json) - CV role-skill index (roles, skills, seniority, language fit)
- [`data/sample_cvs.json`](data/sample_cvs.json) - synthetic, fictional CVs for the scanner demo (no personal data)
- [`data/cv_match_metrics.json`](data/cv_match_metrics.json) - CV matcher evaluation on the synthetic CVs

Artifacts are deterministic enough for judging: model random state is fixed, the same input files produce the same scores and metrics, and only `last_updated` timestamps change on rebuild.

## Run Locally From A Clean Clone

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-ml.txt
python3 scripts/train_career_signal_model.py
python3 scripts/process_career_reality.py
python3 scripts/build_cv_match_index.py
python3 -m http.server 8000
```

Open:

[http://127.0.0.1:8000/index.html](http://127.0.0.1:8000/index.html)

Do not open `index.html` with `file://`; the frontend fetches JSON over HTTP.

## One-Command Rebuild

```bash
./scripts/rebuild_career_reality.sh
```

The script:

1. Runs `scripts/train_career_signal_model.py`
2. Runs `scripts/process_career_reality.py`
3. Validates that all seven challenge artifacts exist and are valid JSON
4. Prints ML and baseline metrics from `data/model_metrics.json`

Expected files:

```text
data/occupation_forecast.json
data/model_metrics.json
data/career_reality.json
data/opportunity_scores.json
data/cv_match_index.json
data/sample_cvs.json
data/cv_match_metrics.json
```

## Docker

Build and run:

```bash
docker build -t swedish-job-pulse .
docker run --rm -p 8000:8000 swedish-job-pulse
```

Then open:

[http://127.0.0.1:8000/index.html](http://127.0.0.1:8000/index.html)

The Dockerfile installs dependencies, rebuilds the ML/data artifacts, and serves the static website. It does not require secrets or private data.

## Deploy: Railway (public app host) + Nebius (AI backend)

The public app is hosted on **[Railway](https://railway.app)** — **not** GitHub Pages.
Railway runs a small FastAPI server ([`app/server.py`](app/server.py)) that does two
things: it serves the existing static frontend, and it **securely proxies** CV-fit
requests to the **Nebius** neural `/cv-fit` endpoint. Nebius is the AI/ML backend;
Railway is the public front door that keeps the Nebius token server-side.

```text
Browser  →  Railway app (app/server.py)  →  Nebius /cv-fit endpoint
            ├── serves index.html / app.js / style.css / data/*.json
            └── POST /api/cv-fit  ──(Authorization: Bearer <token>)──▶  $NEBIUS_CV_FIT_URL/cv-fit
```

**Why a proxy?** The Nebius endpoint is token-protected. The token must never reach
the browser, so the frontend calls the **same-origin** route `POST /api/cv-fit`, and
the server attaches `Authorization: Bearer $NEBIUS_CV_FIT_TOKEN` before forwarding to
`$NEBIUS_CV_FIT_URL/cv-fit`. The Nebius JSON response is returned to the browser
unchanged.

**One analysis path, enforced end to end.** The UI calls `/api/cv-fit`, which
the server forwards to the Nebius **grounded-LLM endpoint**: deterministic TF-IDF
retrieval produces the facts (matched roles, skill gaps, market signal, cross-region
demand) and a self-hosted **Qwen2.5-7B-Instruct** writes the verdict, the
"Why this recommendation?" lines, and the region strategy — constrained to those
facts. An optional **Region** selector tailors it (e.g. a thin local market →
"search Stockholm / Västra Götaland, or go remote"). The proxy checks the live
endpoint health and rejects any response whose backend is not explicitly `llm:...`.
There is no automatic local fallback.

**Railway environment variables** (Project → Variables — server-side only, never
shipped to the browser):

| Variable | Example | Purpose |
|---|---|---|
| `NEBIUS_CV_FIT_URL` | `https://<endpoint>.nebius.cloud` | Base URL of the Nebius endpoint (**no** trailing `/cv-fit` — the server appends it) |
| `NEBIUS_CV_FIT_TOKEN` | `…` | Bearer token for the Nebius endpoint |
| `NEBIUS_CV_FIT_TIMEOUT` | `60` | Optional upstream timeout in seconds (default `60`) |

Railway build/run is configured by [`railway.json`](railway.json) +
[`nixpacks.toml`](nixpacks.toml): it installs only the lightweight
[`requirements-railway.txt`](requirements-railway.txt) (`fastapi`, `uvicorn`, `httpx`
— **not** the ML/data deps) and starts with:

```bash
uvicorn app.server:app --host 0.0.0.0 --port $PORT
```

Health check: `GET /api/health` → `{"status":"ok","neural_available":true|false}`
(reports capability without exposing the URL or token).

**Run the public app locally:**

```bash
python3 -m venv .venv-railway && source .venv-railway/bin/activate
python3 -m pip install -r requirements-railway.txt

# Put the endpoint ID in ignored .env.local:
NEBIUS_CV_FIT_ENDPOINT_ID="<your-endpoint-id>"

# Fetches the endpoint address and token through your authenticated Nebius CLI,
# then starts the local proxy without writing the token to disk:
./scripts/run_local_nebius.sh
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/). See [`env.example`](env.example)
for the variable template. **Privacy:** the proxy forwards CV text to Nebius for the
single request only — it **never logs and never stores** CV text (the uvicorn access
log records the request path `/api/cv-fit`, not the body).

CV reports do not silently fall back to TF-IDF. If the endpoint is unavailable,
the UI displays an error and produces no report.

## Nebius Serverless AI Mapping

Nebius Serverless AI runs containerized AI workloads as Jobs or Endpoints without managing VMs. This project uses **both**:

- **Serverless AI Job** — runs `./scripts/rebuild_career_reality.sh` to build the role index + market artifacts (CPU; deterministic, reproducible).
- **Serverless AI Endpoint — the AI/ML path** — a **grounded-LLM `/cv-fit` advisor on GPU**: deterministic TF-IDF retrieval over the role ontology produces the *facts* (matched roles, skill gaps, market signal, and **cross-region demand ranked by real ad volume**); a self-hosted **Qwen2.5-7B-Instruct** writes the verdict + "why" + region strategy, **constrained to those facts** — it may only use the role titles it is given, so it cannot hallucinate roles or numbers. That is a model-serving + RAG endpoint where the GPU does real work.
- **CPU fallback** — the same image with no model set serves the deterministic TF-IDF report (reproducible; graceful when the GPU is down).

Why grounded generation rather than a bare embedding model: retrieval stays deterministic (reproducible, grounded) while the LLM turns the evidence into genuinely CV- and region-specific advice — e.g. a senior SFMC CV in a thin region is told to go remote or to the regions that actually carry the ad volume.

### Verified deployment

Run on **Nebius Serverless AI** from a public GHCR image (linux/amd64, `ghcr.io/selimsevim/cv-fit-endpoint:llm`):

- **Serverless AI Job** `swedish-job-pulse-rebuild` (`cpu-d3` / `4vcpu-16gb`) — ran `./scripts/rebuild_career_reality.sh` → **COMPLETED**; logs show **7/7 JSON artifacts validated**; CV primary-domain accuracy 1.0, no-collapse 1.0.
- **Grounded-LLM Endpoint** `swedish-job-pulse-cv-fit-llm` (GPU **`gpu-l40s-d` / `1gpu-16vcpu-96gb`, 1× NVIDIA L40S**), token-protected. `GET /health` → `{"status":"ok","backend":"llm:Qwen/Qwen2.5-7B-Instruct","retrieval":"tfidf-fallback","roles":41,"llm":{"model":"Qwen/Qwen2.5-7B-Instruct","ok":true,"device":"cuda"}}`; unauthenticated `POST /cv-fit` → **401**; warm latency **~1.7 s / request**. The **same senior SFMC CV in different regions yields genuinely different, data-grounded advice**:
  - *Stockholms län* → "Stockholm has the strongest local market with 1278 ads."
  - *Norrbottens län / Gotlands län* (thin) → "few ads here — search Stockholm / Västra Götaland, or go remote."
- **CPU TF-IDF endpoint** `swedish-job-pulse-cv-fit` (`cpu-d3` / `4vcpu-16gb`) — **RUNNING**, token-protected; `GET /health` → `{"backend":"tfidf-fallback","roles":41}` — the reproducible fallback.

**Honesty.** Retrieval is deterministic and grounds the LLM (no invented roles or numbers); greedy decoding keeps it reproducible. Sales/marketing isn't broken out per region in the public ad data, so for martech CVs the regional view reads the closest tracked field (**Data/IT**) as a **disclosed proxy** rather than fabricating numbers. Built on **public Arbetsförmedlingen / JobTech job-ad signals, not all jobs in Sweden**. CV text is processed per request and **never stored or logged**. The GPU endpoint bills while running and is deleted after the proof to stop billing.

Detailed Nebius notes, expected inputs/outputs, proof-of-execution screenshots, runtime expectations, and placeholder job commands are in [`nebius/README.md`](nebius/README.md).

Relevant official docs:

- [Nebius Serverless AI overview](https://docs.nebius.com/serverless/overview)
- [Nebius Serverless AI jobs quickstart](https://docs.nebius.com/serverless/quickstart/jobs)

## Repo Layout

```text
.
├── index.html
├── style.css
├── app.js
├── app/                      # Railway public app (static serving + Nebius proxy)
│   └── server.py             # FastAPI: serves frontend, POST /api/cv-fit → Nebius
├── data/
│   ├── live.json
│   ├── history.json
│   ├── occupation_forecast.json
│   ├── model_metrics.json
│   ├── career_reality.json
│   └── opportunity_scores.json
├── scripts/
│   ├── train_career_signal_model.py
│   ├── process_career_reality.py
│   └── rebuild_career_reality.sh
├── nebius/
│   ├── README.md
│   └── cv_fit_endpoint/         # Serverless AI /cv-fit endpoint
│       ├── app.py               # FastAPI: /cv-fit + /health
│       ├── cv_fit_core.py       # deterministic TF-IDF retrieval + ranking (the facts)
│       ├── cv_fit_llm.py        # grounded LLM narrative (Qwen2.5-7B), with fallback
│       ├── Dockerfile.llm        # grounded-LLM GPU image (cv-fit-endpoint:llm)
│       └── requirements-llm.txt
├── docs/
│   └── blog-outline.md
├── railway.json             # Railway build/deploy config (start command, healthcheck)
├── nixpacks.toml            # Railway: install only requirements-railway.txt
├── requirements-railway.txt # Lightweight deps for the Railway app (fastapi/uvicorn/httpx)
├── env.example              # NEBIUS_CV_FIT_URL / NEBIUS_CV_FIT_TOKEN template
├── Dockerfile
├── SUBMISSION_CHECKLIST.md
├── requirements-ml.txt
└── LICENSE
```

## Requirements

For the challenge ML path:

```text
scikit-learn>=1.4
numpy>=1.26
```

The broader data collectors use:

```text
requests==2.32.3
```

## Known Limitations

- This is based on public job-ad signals, not all jobs in Sweden.
- Employers are not generally required to publish every job through Arbetsformedlingen / JobTech.
- Public job ads are demand signals, not a guarantee of employment.
- Search pressure is not the same as applicant count.
- Active ad counts are not official employment totals.
- The ML model improves trend classification, not count MAE.
- The forecast is national by occupation group; regional fit is a transparent specialization weight.
- Entry-level, remote, crowding, and skill momentum signals are approximations from public data.
- CV analysis is advisory and should not be treated as hiring certainty.
- Uploaded or pasted CVs must not be stored.
- Some target-role anchoring uses transparent aliases because user wording and public taxonomy labels do not always match exactly.
- The advice is practical labour-market guidance, not professional counselling.

## Privacy And Secrets

- No personal data
- No private data
- No API keys or tokens required for the local rebuild
- The Nebius token (`NEBIUS_CV_FIT_TOKEN`) lives **only** in Railway environment variables, read server-side by `app/server.py`. It is never embedded in `app.js`, `index.html`, or any file sent to the browser; `env.example` ships placeholders only.
- The Railway proxy **never logs and never stores CV text** — it forwards each CV-fit request to Nebius once and returns the response.
- No `.env` files committed
- `.gitignore` excludes virtual environments, Python caches, `.DS_Store`, logs, local env files, and old screenshot exports

Before submission, run a final secret scan and confirm `git status --short` is clean.

## License

MIT License. See [`LICENSE`](LICENSE).
