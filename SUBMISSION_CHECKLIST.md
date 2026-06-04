# Submission Checklist

Project: Swedish Job Pulse - Career Reality Check

## Links To Fill In

- Public repository URL: `https://github.com/selimsevim/swedish-job-pulse`
- Live website URL: `TODO`
- Technical blog post URL: `TODO`
- Optional demo video URL: `TODO`

## Reproduce From A Clean Clone

```bash
git clone https://github.com/selimsevim/swedish-job-pulse.git
cd swedish-job-pulse
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-ml.txt
./scripts/rebuild_career_reality.sh
python3 -m http.server 8000
```

Open `http://127.0.0.1:8000/index.html`.

## Expected Generated Files

- `data/occupation_forecast.json`
- `data/model_metrics.json`
- `data/career_reality.json`
- `data/opportunity_scores.json`

`./scripts/rebuild_career_reality.sh` validates that each file exists and is valid JSON.

## Metrics To Report

Current `data/model_metrics.json` summary:

- ML MAE: `90.73`
- Baseline MAE: `80.90`
- ML trend accuracy: `0.607`
- Baseline trend accuracy: `0.227`
- ML macro-F1: `0.477`
- Baseline macro-F1: `0.123`
- Samples: `814`
- Holdout: newest `163` samples, temporal split
- Forecast horizon: `4` weeks

Important wording:

The ML model is not used as an exact vacancy-count predictor. Its value is in trend-direction classification, where it outperforms the baseline. The product uses the forecast direction as an advisory signal, while exact counts remain descriptive.

Do not claim that the ML model forecasts vacancy counts better than the baseline; baseline persistence has lower MAE on the current holdout.

## Nebius Proof Needed

Capture these screenshots or logs before final submission:

- Nebius Serverless AI Job 1: public data processing / feature generation
- Nebius Serverless AI Job 2: model training and evaluation
- Nebius Serverless AI Job 3: batch scoring and JSON artifact generation
- Job logs showing the rebuild command and metric summary
- Job output or artifact store listing the four generated JSON files
- Optional Endpoint `/career-signal` request and response, if implemented

No screenshots should include secrets, tokens, private project IDs, or personal data.

## Docker

```bash
docker build -t swedish-job-pulse .
docker run --rm -p 8000:8000 swedish-job-pulse
```

Open `http://127.0.0.1:8000/index.html`.

## Challenge Expectations

- Public repository: confirmed once the GitHub repo is public
- Uses / is prepared for Nebius Serverless AI Jobs: documented in `nebius/README.md`
- Optional Nebius Endpoint mapping: documented as `/career-signal`
- Dockerfile: present
- README setup/runtime/cost/outputs: present
- Open-source license: MIT in `LICENSE`
- No committed secrets/private data: scan before submission
- Technical blog readiness: `docs/blog-outline.md`
- Proof-of-execution readiness: this checklist plus Nebius log targets above

## Known Limitations

- The forecast is national by occupation group; regional fit is a transparent specialization weight, not a regional time-series forecast.
- The model is better than the baseline on trend classification, not count MAE.
- Public job ads are demand signals, not employment guarantees or official labour-force totals.
- Entry-level, remote, crowding, and skill momentum signals are approximations from public data.
- Some target-role matching uses transparent aliases when the public taxonomy lacks the user's exact wording.

## Final Pre-Submit Commands

```bash
./scripts/rebuild_career_reality.sh
python3 -m http.server 8000
git status --short
```

Confirm:

- Working tree is clean
- Rebuild passes
- Website loads
- Career Reality Check works for realistic inputs
- README and blog outline include the MAE nuance
