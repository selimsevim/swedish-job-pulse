# Blog Outline: Swedish Job Pulse - Career Reality Check

Working title:

`A Public-Data Career Reality Check for Sweden with Serverless ML`

Target length: 600-900 words

Hashtag: `#NebiusServerlessChallenge`

## 1. Problem

People in Sweden often spend weeks applying to roles without knowing whether the role is realistic for their region, experience level, language level, and study runway. Job boards answer "what jobs exist?" but not "is this path realistic for me right now?"

The goal is not to build a generic career coach. The goal is a public-data career reality check: use Swedish labour-market signals to separate realistic-now paths, reachable paths, and risky or crowded paths.

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
- The frontend reads `data/career_reality.json` and `data/opportunity_scores.json`.
- There is no backend, database, authentication, or live LLM dependency.

Serverless mapping:

- Job 1: public data processing and feature generation.
- Job 2: ML training and evaluation.
- Job 3: batch scoring and JSON artifact generation.
- Optional Endpoint `/career-signal`: live per-user scoring using the same artifacts.

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

The user enters:

- Region
- Swedish level
- Current experience area
- Target job
- Skills
- Experience level
- Remote preference
- Study willingness

The website returns:

- Verdict: realistic now, reachable in 3-6 months, risky for now, or not enough signal
- Evidence panel: trend, forecast, crowding risk, entry-level signal, remote signal, regional fit, matched skills
- Three role buckets: realistic now, reachable with upgrades, risky/crowded
- Skills to add
- Search keywords in Swedish and English
- Concrete 2-week action plan

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

Proof to include:

- Job logs showing `./scripts/rebuild_career_reality.sh`
- Metric summary from `data/model_metrics.json`
- Artifact listing or commit diff
- Optional Endpoint request/response if implemented

## 8. Limitations

- National occupation forecast only; regional fit is a transparent specialization weight.
- Public job ads are a proxy for labour demand, not a guarantee of employment.
- Entry-level, remote, crowding, and skill momentum signals are approximate.
- Some exact user target titles are mapped to broader public taxonomy fields.
- Model count MAE does not beat baseline persistence; direction metrics are the reason the ML signal is useful.

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
