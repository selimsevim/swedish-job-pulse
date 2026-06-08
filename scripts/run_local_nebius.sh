#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env.local ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
fi

: "${NEBIUS_CV_FIT_ENDPOINT_ID:?Set NEBIUS_CV_FIT_ENDPOINT_ID in .env.local}"

NEBIUS_BIN="${NEBIUS_BIN:-$HOME/.nebius/bin/nebius}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv-railway/bin/python}"

if [[ ! -x "$NEBIUS_BIN" ]]; then
  echo "Nebius CLI not found at $NEBIUS_BIN" >&2
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Railway virtualenv not found. Install requirements-railway.txt first." >&2
  exit 1
fi

endpoint_json="$("$NEBIUS_BIN" ai endpoint get "$NEBIUS_CV_FIT_ENDPOINT_ID" --format json)"
endpoint_state="$(jq -r '.status.state // empty' <<<"$endpoint_json")"
endpoint_address="$(jq -r '.status.public_endpoints[0] // empty' <<<"$endpoint_json")"
endpoint_token="$(jq -r '.spec.auth_token // empty' <<<"$endpoint_json")"

if [[ "$endpoint_state" != "RUNNING" ]]; then
  echo "Nebius endpoint is not running (state: ${endpoint_state:-unknown})." >&2
  exit 1
fi
if [[ -z "$endpoint_address" || -z "$endpoint_token" ]]; then
  echo "Nebius endpoint address or token is unavailable." >&2
  exit 1
fi

export NEBIUS_CV_FIT_URL="http://$endpoint_address"
export NEBIUS_CV_FIT_TOKEN="$endpoint_token"
export NEBIUS_CV_FIT_TIMEOUT="${NEBIUS_CV_FIT_TIMEOUT:-90}"

echo "Starting local app with Nebius LLM endpoint at $endpoint_address"
exec "$PYTHON_BIN" -m uvicorn app.server:app \
  --host "${HOST:-127.0.0.1}" \
  --port "${PORT:-8000}"
