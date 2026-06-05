# Swedish Job Pulse

Swedish Job Pulse is a public-data career guidance website for people in Sweden. It has two ways in:

1. **CV Job Fit Scanner** (primary) &mdash; upload a PDF CV or paste CV text and get a one-page CV-to-market fit report: best-fit roles now, stretch roles, roles to avoid for now, missing skills, CV fixes, search keywords and a 7-day plan.
2. **Career Reality Check** (fallback) &mdash; answer a few questions (target job, region, skills, level) instead of uploading a CV.

It answers one practical question:

> Before you spend weeks applying, is this role realistic for you in the current Swedish labour market &mdash; and if not, what should you apply for and add?

This is not a job board and not a generic AI career coach. It is a static website backed by public Arbetsformedlingen / JobTech labour-market data, an occupation demand trend forecast, a role-skill index, and transparent scoring rules for crowding risk, entry-level access, regional fit, remote signal, and skill momentum.

## CV Job Fit Scanner

Upload a PDF CV, or paste CV text, &rarr; get a one-page job-fit report.

**Privacy / reproducibility.** PDFs are parsed **entirely in your browser** with pdf.js, and pasted CV text is analyzed locally in the page. CV content is **never uploaded and never stored**, and no real CV is committed to this repo. The challenge build is demoed and evaluated only on **synthetic, fictional CVs** in [`data/sample_cvs.json`](data/sample_cvs.json).

Three layers:

- **Extraction** &mdash; PDF or pasted CV text is parsed in-browser into `{skills, roles, languages, seniority}`.
- **Retrieval + ranking** &mdash; the profile is vectorized and matched against a role ontology ([`data/cv_match_index.json`](data/cv_match_index.json)), then reranked by skill overlap, seniority, domain fit and Swedish-language fit, enriched with public demand / crowding / regional / trend signals. The shipped static site uses a reproducible **multilingual TF-IDF vector space** with synonym/domain expansion (so `SFMC == Salesforce Marketing Cloud == Martech` and a technical martech CV is not flattened into "digital marketing"). The hand-written synonym list is a **bootstrap**; the scalable replacement is a **neural embedding model (BGE-M3 / Qwen3) at the Nebius `/cv-fit` endpoint** (no synonym list needed) — see [`nebius/README.md`](nebius/README.md).
- **Gap analysis** &mdash; what blocks stronger matches: missing skills, weak proof, language.

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

## Nebius Serverless AI Mapping

Nebius Serverless AI runs containerized AI workloads as Jobs or Endpoints without managing VMs or clusters. This project maps to that model as batch JSON artifact generation:

- Job 1: public data processing / feature generation
- Job 2: ML training and evaluation
- Job 3: batch scoring and JSON artifact generation
- Optional Endpoint: `/cv-fit` for server-side CV analysis (neural embeddings are scaffolded and env-gated; see below)

The current workload is CPU-friendly. A GPU is unnecessary for the dataset size; runtime is dominated by JSON parsing and a small scikit-learn model.

### Verified deployment

Both the Job and the Endpoint were run on **Nebius Serverless AI** (platform `cpu-d3`, preset `4vcpu-16gb`), pulling the public GHCR images:

- **Serverless AI Job** `swedish-job-pulse-rebuild` — ran `./scripts/rebuild_career_reality.sh` and reached **COMPLETED**. Logs show **7/7 JSON artifacts validated** and the metrics: ML MAE 90.73 vs baseline 80.90; ML trend accuracy 0.61 vs 0.23; ML macro-F1 0.48 vs 0.12; CV primary-domain accuracy 1.0; CV no-collapse 1.0.
- **Serverless AI Endpoint** `swedish-job-pulse-cv-fit` — **RUNNING**, token-protected. `GET /health` → `{"status":"ok","backend":"tfidf-fallback","roles":41}`; `POST /cv-fit` → 200 with the full report for a synthetic SFMC CV; an unauthenticated `POST /cv-fit` returns **401**.

The deployed proof used the **TF-IDF fallback** backend. The neural BGE-M3 / Qwen3 embedding path is **scaffolded and env-gated** (`CV_FIT_EMBEDDING_MODEL`) but was **not** run in this deployment. The trend model is used for **direction** (grow/stable/decline), **not** exact vacancy-count prediction — baseline persistence has lower count MAE. The platform is built on **public Arbetsförmedlingen / JobTech job-ad signals, not all jobs in Sweden**. The endpoint is **token-protected**, and **CV text is processed per request and not stored**.

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
│   └── README.md
├── docs/
│   └── blog-outline.md
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
- No `.env` files committed
- `.gitignore` excludes virtual environments, Python caches, `.DS_Store`, logs, local env files, and old screenshot exports

Before submission, run a final secret scan and confirm `git status --short` is clean.

## License

MIT License. See [`LICENSE`](LICENSE).
