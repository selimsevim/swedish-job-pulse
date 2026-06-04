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
  -> Static website
```

No credentials are hardcoded here. Nebius authentication, registry credentials, or object-storage credentials must be provided at runtime through the Nebius platform, CLI profile, or secret store.

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

## One Combined Serverless Job

For a simple challenge proof, Jobs 2 and 3 can run as one finite Serverless AI Job:

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

## Optional Endpoint - `/career-signal`

The website does not require a live endpoint. It reads precomputed JSON files.

If an Endpoint is added later, it should expose the same scoring logic for live user-profile requests:

```http
POST /career-signal
Content-Type: application/json
```

Example request:

```json
{
  "region": "Stockholms län",
  "swedish_level": "good",
  "experience": "customer_service",
  "target": "data analyst",
  "skills": ["excel", "sql"],
  "level": "entry",
  "remote": "nice",
  "study": "mid"
}
```

Example response shape:

```json
{
  "verdict": "reachable",
  "opportunity_score": 58,
  "evidence": {
    "forecast_direction": "grow",
    "crowding_risk": "medium",
    "entry_level_signal": "weak",
    "regional_fit": "medium"
  },
  "next_actions": ["Apply to nearby roles", "Add SQL", "Build a small reporting portfolio"]
}
```

This is intentionally marked optional because the challenge story works with Jobs alone: public data processing, ML training, batch scoring, and static delivery.

## Hardware And Cost Notes

- CPU is enough for all current scripts.
- The dataset is small: the four challenge artifacts total under 1 MB in the current repo.
- No persistent server is required after artifacts are generated.
- Serverless Jobs are a good fit because the workload starts, writes artifacts, and exits.
- Endpoint costs should be avoided unless live per-request scoring is actually needed.

## Submission Proof Checklist

Capture:

- Serverless Job configuration showing the public container image
- Job logs for rebuild command and metrics
- Generated artifact listing or commit diff
- Static website screenshot after artifact generation
- Optional Endpoint request/response if implemented

Do not capture:

- API tokens
- Nebius credentials
- Private registry credentials
- Personal user data
- Private project IDs if you do not want them public
