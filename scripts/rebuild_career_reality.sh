#!/usr/bin/env bash
#
# One-command rebuild for the Career Reality Check ML pipeline.
#
# Judges should not need to understand five scripts. This rebuilds everything
# the platform needs, validates the artifacts, and prints the headline metric
# comparison (read live from model_metrics.json, never hardcoded).
#
#   ./scripts/rebuild_career_reality.sh
#
# It runs:
#   1. scripts/train_career_signal_model.py   (ML demand forecast + evaluation)
#   2. scripts/process_career_reality.py      (scoring + advice artifacts)
#
# then validates these exist and are valid JSON:
#   data/occupation_forecast.json
#   data/model_metrics.json
#   data/career_reality.json
#   data/opportunity_scores.json
#
# Python selection (override with PYTHON=/path/to/python):
#   $PYTHON  ->  repo venv (has scikit-learn)  ->  python3
# Without scikit-learn the pipeline still succeeds on a deterministic baseline.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
elif [ -x "venv/bin/python" ]; then
  PY="venv/bin/python"
else
  PY="python3"
fi

echo "==> Python: $PY ($("$PY" --version 2>&1))"

echo
echo "==> [1/2] Training demand-forecast model..."
"$PY" scripts/train_career_signal_model.py

echo
echo "==> [2/2] Building Career Reality Check artifacts..."
"$PY" scripts/process_career_reality.py

echo
echo "==> Validating output JSON..."
FILES=(
  data/occupation_forecast.json
  data/model_metrics.json
  data/career_reality.json
  data/opportunity_scores.json
)
fail=0
for f in "${FILES[@]}"; do
  if [ ! -f "$f" ]; then
    echo "    MISSING:      $f"
    fail=1
  elif "$PY" -c "import json,sys; json.load(open(sys.argv[1]))" "$f" 2>/dev/null; then
    echo "    OK:           $f"
  else
    echo "    INVALID JSON: $f"
    fail=1
  fi
done
if [ "$fail" -ne 0 ]; then
  echo
  echo "==> FAILED: one or more artifacts are missing or invalid." >&2
  exit 1
fi

echo
echo "================ MODEL EVALUATION (data/model_metrics.json) ================"
"$PY" - <<'PYEOF'
import json
m = json.load(open("data/model_metrics.json")).get("metrics", {})
model = m.get("model")
base = m.get("baseline_persistence") or {}

def fmt(x):
    return f"{x:.2f}" if isinstance(x, (int, float)) else "n/a"

if model:
    print(f"  ML trend accuracy:        {fmt(model.get('trend_accuracy'))}")
    print(f"  Baseline trend accuracy:  {fmt(base.get('trend_accuracy'))}")
    print(f"  ML macro-F1:              {fmt(model.get('trend_macro_f1'))}")
    print(f"  Baseline macro-F1:        {fmt(base.get('trend_macro_f1'))}")
    print(f"  (ML MAE {fmt(model.get('mae'))} vs baseline MAE {fmt(base.get('mae'))} "
          f"| {m.get('n_samples')} samples, horizon {m.get('horizon_weeks')} weeks)")
else:
    print("  ML model not trained (scikit-learn not installed).")
    print("  Forecasts came from the deterministic baseline — the site still works.")
    print("  To reproduce the headline ML metrics, install the optional deps:")
    print("      python3 -m pip install -r requirements-ml.txt")
PYEOF
echo "============================================================================"

echo
echo "==> Done. View the site with:  python3 -m http.server 8000"
