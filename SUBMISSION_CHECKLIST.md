# Submission Checklist

Project: Swedish Job Pulse - CV-to-Swedish-job-market fit engine

## Submission Fields To Fill In

- Repository URL: `https://github.com/selimsevim/swedish-job-pulse`
- Live website URL: `TODO` (public host: **Railway** — `app/server.py` serves the frontend and proxies `POST /api/cv-fit` to the Nebius endpoint; set `NEBIUS_CV_FIT_URL` + `NEBIUS_CV_FIT_TOKEN` as Railway variables. Not GitHub Pages.)
- Nebius Job: ✅ ran on Nebius Serverless AI (platform `cpu-d3`) — state COMPLETED; logs + status in local `challenge_evidence/` (gitignored)
- Nebius Endpoint `/cv-fit`: ✅ **grounded-LLM endpoint** `swedish-job-pulse-cv-fit-llm` on **GPU `gpu-l40s-d` (1× L40S)**, image `ghcr.io/selimsevim/cv-fit-endpoint:llm`, token auth — deterministic TF-IDF retrieval grounds **Qwen2.5-7B-Instruct**; `/health`, 401, and region-varying `/cv-fit` verified (proof in local `challenge_evidence/`). CPU TF-IDF endpoint `swedish-job-pulse-cv-fit` is the reproducible fallback.
- Blog post URL: `TODO`
- Video URL: `TODO`
- Docker build confirmation: ✅ root + endpoint images build (linux/amd64), run, and are published to public GHCR (`ghcr.io/selimsevim/swedish-job-pulse`, `ghcr.io/selimsevim/cv-fit-endpoint` incl. the `:llm` grounded-LLM tag)
- Rebuild command confirmation: ✅ `./scripts/rebuild_career_reality.sh` passes locally and inside the Nebius Job
- Metrics summary: ML MAE 90.73 / baseline 80.90; trend acc 0.61 / 0.23; macro-F1 0.48 / 0.12; CV primary-domain 1.0, no-collapse 1.0
- Known limitations: see "Known Limitations" below
- License confirmed: MIT (`LICENSE`)
- No secrets confirmed: ✅ scan clean; CVs processed per request, not stored

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
- `data/cv_match_index.json`
- `data/sample_cvs.json`
- `data/cv_match_metrics.json`

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

## Nebius Proof — verified 2026-06-05

Both ran on Nebius Serverless AI (region eu-north1, platform `cpu-d3`, preset
`4vcpu-16gb`), pulling public GHCR images:

- **Serverless AI Job** (`swedish-job-pulse-rebuild`): ran
  `./scripts/rebuild_career_reality.sh` end-to-end and reached **COMPLETED**.
  Logs show all three stages (forecast training → scoring → CV index build),
  7/7 JSON artifacts validated, and the metrics: ML MAE 90.73 vs baseline 80.90;
  ML trend accuracy 0.61 vs 0.23; ML macro-F1 0.48 vs 0.12; CV primary-domain
  accuracy 1.0, no-collapse rate 1.0. (The "Job 1/2/3" split is the conceptual
  mapping; a single Serverless Job runs all three stages.)
- **Serverless AI Endpoint** (`swedish-job-pulse-cv-fit`): **RUNNING** with a
  public address and token auth. `GET /health` → `{"status":"ok",
  "backend":"tfidf-fallback","roles":41}`; `POST /cv-fit` → 200 with the full
  report; unauthenticated `POST /cv-fit` → HTTP 401.

Raw resource IDs, the public URL, full logs and responses are kept in local
`challenge_evidence/` (gitignored — it contains account/project IDs and is not
committed). No tokens, project IDs, or personal data are committed to the repo.

> The endpoint is a paid running resource. Tear it down when no longer needed:
> `nebius ai endpoint delete <ENDPOINT_ID>` (ID in `challenge_evidence/`).

## Docker

```bash
docker build -t swedish-job-pulse .
docker run --rm -p 8000:8000 swedish-job-pulse
```

Open `http://127.0.0.1:8000/index.html`.

## Challenge Expectations

- Public repository: confirmed once the GitHub repo is public
- Uses / is prepared for Nebius Serverless AI Jobs: documented in `nebius/README.md`
- Optional Nebius Endpoint mapping: implemented and documented as `/cv-fit`
- Dockerfile: present
- README setup/runtime/cost/outputs: present
- Open-source license: MIT in `LICENSE`
- No committed secrets/private data: scan before submission
- Technical blog readiness: `docs/blog-outline.md`
- Proof-of-execution readiness: this checklist plus Nebius log targets above

## Known Limitations

- The forecast is national by occupation group; regional fit is a transparent specialization weight, not a regional time-series forecast.
- The model is better than the baseline on trend classification, not count MAE.
- This is based on public job-ad signals, not all jobs in Sweden.
- Employers are not generally required to publish every job through Arbetsformedlingen / JobTech.
- Public job ads are demand signals, not employment guarantees or official labour-force totals.
- Search pressure is not the same as applicant count.
- CV analysis is advisory and should not be treated as hiring certainty.
- Uploaded or pasted CVs must not be stored.
- Entry-level, remote, crowding, and skill momentum signals are approximations from public data.
- Some target-role matching uses transparent aliases when the public taxonomy lacks the user's exact wording.

## Final Pre-Submit Commands

```bash
./scripts/rebuild_career_reality.sh
python3 nebius/cv_fit_endpoint/test_cv_fit.py
python3 -m http.server 8000
git status --short
```

Confirm:

- Working tree is clean
- Rebuild passes
- Website loads
- CV Job Fit Scanner works for realistic, weak, and synthetic inputs
- README and blog outline include the MAE nuance
