# Running Career Reality Check on Nebius Serverless AI Jobs

Swedish Job Pulse is **static-first**: the website is plain HTML/CSS/JS that reads
generated JSON files. Nothing here requires a live backend, credentials, or a
running model server. This folder explains how the data + ML layer behind
**Career Reality Check** maps onto [Nebius](https://nebius.com) Serverless AI
Jobs so it can run on a schedule in the cloud and commit fresh artifacts.

> **Positioning:** *A serverless ML career-signal engine that forecasts Swedish
> labour-market demand and turns public job-market data into practical career
> advice.*

Nothing in this folder reads secrets. Do **not** commit credentials. Nebius auth
is provided at run time through the platform (environment / secret store), never
checked into the repo.

---

## The pipeline as serverless jobs

The local rebuild sequence (see the main [`README.md`](../README.md)) breaks
cleanly into three jobs plus an optional endpoint. Each job reads and writes
plain JSON under `data/`; that shared artifact store (object storage / a
committed `data/` directory) is the only thing they share.

```
          ┌─────────────────────────────────────────────────────────┐
          │  public JobTech / Arbetsförmedlingen APIs (no API key)    │
          └─────────────────────────────────────────────────────────┘
                                   │
              ┌────────────────────▼─────────────────────┐
   Job 1 ──▶  data processing      collect.py, process_*  │ ──▶ data/*.json
              └────────────────────┬─────────────────────┘
                                   │ history.json, demand_gap.json, ...
              ┌────────────────────▼─────────────────────┐
   Job 2 ──▶  model training       train_career_signal_   │ ──▶ occupation_forecast.json
              + evaluation         model.py               │     model_metrics.json
              └────────────────────┬─────────────────────┘
                                   │
              ┌────────────────────▼─────────────────────┐
   Job 3 ──▶  batch scoring +      process_career_reality │ ──▶ career_reality.json
              JSON generation      .py                    │     opportunity_scores.json
              └────────────────────┬─────────────────────┘
                                   │
                          static website reads data/*.json
                                   │
   Endpoint (optional) ──▶ /career-signal  live per-request scoring
```

### Job 1 — data processing

Refreshes the raw market datasets from public APIs.

```bash
python3 scripts/collect.py
python3 scripts/process_skill_velocity.py
python3 scripts/process_demand_gap.py
python3 scripts/process_regional_split.py
# (process_decay.py, process_ad_lifespan.py as needed)
```

* **Inputs:** public JobTech APIs (no key required).
* **Outputs:** `data/live.json`, `data/history.json`, `data/skill_velocity.json`,
  `data/demand_gap.json`, `data/regional_split.json`, ...
* **Runtime:** CPU-only, light. Standard library + `requests`.

### Job 2 — model training and evaluation

Trains the demand-forecast model and writes the forecast + evaluation.

```bash
python3 -m pip install -r requirements-ml.txt   # scikit-learn, numpy
python3 scripts/train_career_signal_model.py
```

* **Inputs:** `data/history.json`, `data/live.json`, `data/demand_gap.json`.
* **Outputs:** `data/occupation_forecast.json`, `data/model_metrics.json`.
* **What it does:** builds a supervised dataset of lag features per occupation
  group, trains a `HistGradientBoostingRegressor` (4-week-ahead demand), and
  benchmarks it against a moving-average / persistence baseline. Reports MAE,
  MAPE, and trend-direction accuracy + macro-F1.
* **Fallback-safe:** if `scikit-learn` is not installed or there is too little
  history, it produces forecasts from the deterministic baseline and flags
  `model_source: "baseline"`. The job never fails the pipeline.
* **Runtime:** CPU-only is enough for this dataset size. A small CPU Serverless
  Job is the right fit; GPU is unnecessary at current scale.

### Job 3 — batch scoring and JSON generation

Combines the forecast with the rule-based signals into the UI-ready artifacts.

```bash
python3 scripts/process_career_reality.py
```

* **Inputs:** all `data/*.json` above, including `occupation_forecast.json`
  (optional — falls back to history/rule-based trend if absent).
* **Outputs:** `data/career_reality.json` (full UI model),
  `data/opportunity_scores.json` (compact occupation × region signal table).
* **Runtime:** CPU-only, light, standard library only.

After Job 3 commits/uploads the new `data/*.json`, the static site serves the
fresh advice with no redeploy.

---

## Optional endpoint — `/career-signal`

For live, per-request scoring (instead of pre-baked JSON), the same model can be
wrapped behind a Nebius Serverless **Endpoint**:

```
POST /career-signal
{
  "region": "Stockholms län",
  "swedish_level": "english",
  "experience": "customer_service",
  "target": "data analyst",
  "skills": ["excel", "sql"],
  "level": "entry",
  "remote": "important",
  "study": "mid"
}
→ { "verdict": "soon", "opportunity_score": 58,
    "realistic_now": [...], "reachable": [...], "risky": [...],
    "skills_to_add": [...], "forecast": { "trend_class": "grow", ... } }
```

The endpoint would load `occupation_forecast.json` + `career_reality.json` (or
the trained model artifact) and run the same matching logic that lives in
`app.js` today. This is **optional**: the website does not depend on it.

---

## Scheduling

A weekly cadence matches the data source. Run **Job 1 → Job 2 → Job 3** in order
(Job 3 consumes Job 2's forecast). The existing GitHub Actions workflow already
runs Job 1's `collect.py` weekly; the same three steps can run as scheduled
Nebius Serverless Jobs, writing artifacts back to object storage or committing
to `data/`.

## Future work (Job 2, expanded)

* Persist a weekly **occupation × region** feed so the forecast can be trained
  per region pair, not only nationally (today region enters as a transparent
  specialisation weight in Job 3 — see the note in
  `train_career_signal_model.py`).
* Try LightGBM / XGBoost and longer horizons (8 weeks) once more history
  accumulates.
* Add quantile forecasts for confidence bands.
