#!/usr/bin/env bash
# Full demo — console + optional auto-investigation when StreamIngestCrashLooping fires.
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
echo "==> Starting console (alert watcher enabled)"
echo "    1. Open http://localhost:8501"
echo "    2. In another terminal: task break"
echo "    3. Wait ~1m for StreamIngestCrashLooping — investigation auto-starts"
echo

export BALLAST_ALERT_WATCH=1
exec ./scripts/run-console.sh
