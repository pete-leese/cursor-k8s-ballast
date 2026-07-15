#!/usr/bin/env bash
# Start the Ballast API and Streamlit console on the host.
# Requires Prometheus reachable (task cluster:forward) for live engine triage.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PY=./.venv/bin/python
$PY -c "import fastapi, streamlit" 2>/dev/null || {
  echo "==> Installing console dependencies into .venv"
  $PY -m pip install -q -r requirements.txt
}

echo "==> Ballast API on http://localhost:8000"
echo "    Investigator: ${BALLAST_INVESTIGATOR:-engine}  Alert watch: ${BALLAST_ALERT_WATCH:-0}  Auto-remediate: ${BALLAST_AUTO_REMEDIATE:-0}"
BALLAST_ALERT_WATCH="${BALLAST_ALERT_WATCH:-0}" \
BALLAST_AUTO_REMEDIATE="${BALLAST_AUTO_REMEDIATE:-$([ -n "${CURSOR_API_KEY:-}" ] && echo 1 || echo 0)}" \
  $PY -m uvicorn ballast.api:app --host 0.0.0.0 --port 8000 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT

sleep 2
echo "==> Ballast console on http://localhost:8501"
echo "    Induce incident: task break  (investigate manually from the console; set BALLAST_ALERT_WATCH=1 to auto-start on alert)"
BALLAST_API_URL="http://localhost:8000" \
  $PY -m streamlit run console/app.py \
  --server.address=0.0.0.0 --server.port=8501 --server.headless=true
