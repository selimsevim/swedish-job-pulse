# Blog Outline: Swedish Job Pulse - CV Job Fit Scanner

Working title:

`A Public-Data CV-to-Job-Market Fit Engine for Sweden with Serverless ML`

Target length: 600-900 words

Hashtag: `#NebiusServerlessChallenge`

## 1. Problem

People in Sweden often spend weeks applying to roles without knowing whether their actual CV fits the public job-ad market. Job boards answer "what jobs exist?" but not "which role family does this CV credibly match right now?"

The goal is not to build a generic career coach or a complete view of every Swedish job. The goal is a public-data CV-to-market fit layer: extract a career identity from a CV, match it to a Swedish role ontology, then add public job-ad market signals.

## 2. Why Public Job Data

Use Arbetsformedlingen / JobTech public data because it gives transparent market signals without private user data:

- Active ad counts by occupation group
- Entry-level and remote shares by occupation field
- Regional occupation-field specialization
- Search attention versus demand for crowding risk
- Skill mention momentum from historical archives

The system uses no personal data, no private datasets, and no API keys.

## 3. Architecture

Static-first architecture:

- Python data and ML scripts generate JSON artifacts.
- The website is plain HTML/CSS/JS.
- The frontend reads `data/cv_match_index.json`, `data/career_reality.json`, and synthetic sample CVs.
- The static site uses TF-IDF vector retrieval with synonym/domain expansion.
- There is no backend, database, authentication, or live LLM dependency for the static baseline.
- Optional `/cv-fit` endpoint uses neural embeddings such as BGE-M3/Qwen-style models when available, with TF-IDF fallback.

Serverless mapping:

- Job 1: public data processing and feature generation.
- Job 2: ML training and evaluation.
- Job 3: batch scoring and JSON artifact generation.
- Job 4: CV role-skill index build and synthetic CV evaluation.
- Optional Endpoint `/cv-fit`: server-side CV matching with neural embeddings when available.

## 4. ML Approach

The ML layer forecasts occupation-group demand direction over a 4-week horizon.

Training data:

- Weekly history from `data/history.json`
- Occupation-group active-ad counts
- Lag features: previous week, 4-week average, 8-week average, 4-week relative trend
- Context features: remote share, entry-level share, search-attention gap, occupation-field code

Model:

- `HistGradientBoostingRegressor`
- Temporal split: newest target weeks are the holdout set
- Random state fixed for reproducibility
- Pure-stdlib fallback emits a baseline forecast if scikit-learn is unavailable

## 5. Baseline Comparison

Report the current metrics exactly:

- ML MAE: `90.73`
- Baseline MAE: `80.90`
- ML trend accuracy: `0.607`
- Baseline trend accuracy: `0.227`
- ML macro-F1: `0.477`
- Baseline macro-F1: `0.123`
- Samples: `814`
- Forecast horizon: `4` weeks

Important interpretation:

The ML model is not used as an exact vacancy-count predictor. Its value is in trend-direction classification, where it outperforms the persistence baseline. The product uses forecast direction as an advisory signal. Exact counts remain descriptive and should not be presented as precise predictions.

Avoid claiming that the ML model forecasts counts better than the baseline.

## 6. Website Output

The primary user flow:

- Upload a PDF CV or paste CV text.
- Extract skills, role language, seniority, tools, and language signal in-browser.
- Match the profile to a role ontology with TF-IDF cosine similarity and reranking.
- Add public market context: demand direction, crowding, regional fit, remote signal.

The website returns:

- Main answer
- Best-fit roles now
- Adjacent / stretch roles
- Not your main lane
- Missing skills and CV improvements
- Search keywords
- 7-day action plan
- Compact market signal

## 7. Nebius Serverless AI Jobs Mapping

Explain why this fits Serverless AI Jobs:

- The workload is finite and batch-oriented.
- It produces static JSON artifacts.
- It does not need an always-on server.
- CPU is enough for the current dataset; GPU is unnecessary.
- The same container can run scheduled data refreshes and training.

Artifacts produced:

- `data/occupation_forecast.json`
- `data/model_metrics.json`
- `data/career_reality.json`
- `data/opportunity_scores.json`
- `data/cv_match_index.json`
- `data/sample_cvs.json`
- `data/cv_match_metrics.json`

Verified deployment (run on Nebius Serverless AI, platform `cpu-d3`, preset `4vcpu-16gb`, public GHCR images):

- **Serverless AI Job** `swedish-job-pulse-rebuild` ran `./scripts/rebuild_career_reality.sh`
  to COMPLETED: 7/7 JSON artifacts validated; ML MAE 90.73 vs baseline 80.90;
  ML trend accuracy 0.61 vs 0.23; ML macro-F1 0.48 vs 0.12; CV primary-domain
  accuracy 1.0; CV no-collapse 1.0.
- **Serverless AI Endpoint** `swedish-job-pulse-cv-fit` is RUNNING and
  token-protected: `/health` -> `{"status":"ok","backend":"tfidf-fallback","roles":41}`;
  `/cv-fit` -> 200 with the full report for a synthetic SFMC CV; an
  unauthenticated POST returns 401.

Be precise in the post:

- The deployed proof used the **TF-IDF fallback**; the neural BGE-M3 / Qwen3
  path is scaffolded and env-gated but was **not** run.
- The trend model is used for **direction**, not exact vacancy-count prediction
  (baseline has lower count MAE).
- Built on **public job-ad signals, not all Swedish jobs**.
- The endpoint is token-protected and CV text is processed per request, not stored.
- Do not publish resource IDs, the public IP, tokens, or project/registry IDs.

## 8. Limitations

- National occupation forecast only; regional fit is a transparent specialization weight.
- Public job ads are a proxy for labour demand, not a guarantee of employment and not all jobs in Sweden.
- Employers are not generally required to publish every job through Arbetsformedlingen / JobTech.
- Search pressure is not the same as applicant count.
- Entry-level, remote, crowding, and skill momentum signals are approximate.
- Some exact user target titles are mapped to broader public taxonomy fields.
- Model count MAE does not beat baseline persistence; direction metrics are the reason the ML signal is useful.
- CV analysis is advisory and should not be treated as hiring certainty.
- Uploaded or pasted CVs must not be stored.

## 9. Reproducibility

```bash
git clone https://github.com/selimsevim/swedish-job-pulse.git
cd swedish-job-pulse
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-ml.txt
./scripts/rebuild_career_reality.sh
python3 -m http.server 8000
```

Docker:

```bash
docker build -t swedish-job-pulse .
docker run --rm -p 8000:8000 swedish-job-pulse
```

Close with:

This project is a practical example of using serverless ML for public-interest decision support: not replacing human judgement, but making labour-market risk visible before people spend weeks applying.
