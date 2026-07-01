#!/usr/bin/env bash
# Mint a read-only (Viewer) Grafana service-account token for the official
# mcp-grafana server. Requires Grafana reachable (port-forward first):
#   kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
#
# Usage: ./scripts/grafana-token.sh
# Env: GRAFANA_URL (default http://localhost:3000), GRAFANA_ADMIN (default admin),
#      GRAFANA_ADMIN_PASSWORD (default admin — see clusters/monitoring-values.yaml)
set -euo pipefail

URL="${GRAFANA_URL:-http://localhost:3000}"
ADMIN="${GRAFANA_ADMIN:-admin}"
PASS="${GRAFANA_ADMIN_PASSWORD:-admin}"
NAME="ballast-mcp-$(date +%s)"

echo "==> Creating Viewer service account '${NAME}' in ${URL}" >&2
sa_id=$(curl -fsS -u "${ADMIN}:${PASS}" -H "Content-Type: application/json" \
  -X POST "${URL}/api/serviceaccounts" \
  -d "{\"name\":\"${NAME}\",\"role\":\"Viewer\"}" | \
  "$(dirname "$0")/../.venv/bin/python" -c "import sys,json;print(json.load(sys.stdin)['id'])")

token=$(curl -fsS -u "${ADMIN}:${PASS}" -H "Content-Type: application/json" \
  -X POST "${URL}/api/serviceaccounts/${sa_id}/tokens" \
  -d "{\"name\":\"${NAME}-token\"}" | \
  "$(dirname "$0")/../.venv/bin/python" -c "import sys,json;print(json.load(sys.stdin)['key'])")

echo "==> Add these to your .env (used by mcp-grafana in .mcp.json):" >&2
echo "GRAFANA_URL=${URL}"
echo "GRAFANA_SERVICE_ACCOUNT_TOKEN=${token}"
