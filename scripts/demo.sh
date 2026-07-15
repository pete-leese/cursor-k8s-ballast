#!/usr/bin/env bash
# Full demo — console with manual (button-triggered) investigations by default.
# Auto-investigation on StreamIngestCrashLooping is opt-in: BALLAST_ALERT_WATCH=1 ./scripts/demo.sh
# Prereqs: task cluster:up, task deploy, task cluster:forward (separate terminal).
set -euo pipefail
cd "$(dirname "$0")/.."

PROM="${PROMETHEUS_URL:-http://localhost:9090}"
if ! curl -fsS "${PROM}/-/ready" >/dev/null 2>&1; then
  echo "ERROR: Prometheus not reachable at ${PROM}" >&2
  echo "       Run 'task cluster:forward' in another terminal first." >&2
  exit 1
fi

echo "==> Prometheus OK at ${PROM}"
echo "==> Starting console (alert watch: ${BALLAST_ALERT_WATCH:-0} — 0 = manual investigations)"
echo "    1. Open http://localhost:8501"
echo "    2. In another terminal: task break"
echo "    3. Wait ~1m for StreamIngestCrashLooping, then trigger the investigation from the console"
echo "       (set BALLAST_ALERT_WATCH=1 to auto-start investigations when the alert fires)"
echo

export BALLAST_ALERT_WATCH="${BALLAST_ALERT_WATCH:-0}"
exec ./scripts/run-console.sh
