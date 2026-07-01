#!/usr/bin/env bash
# Restore a healthy memory limit (the forward-fix the RCA recommends).
# Usage: ./scripts/fix.sh [SERVICE] [GOOD_MEMORY]
#   defaults: payments 128Mi
set -euo pipefail
cd "$(dirname "$0")/.."

SERVICE="${1:-payments}"
GOOD_MEM="${2:-128Mi}"

echo "==> Forward-fix: ${SERVICE} resources.limits.memory=${GOOD_MEM}"
helm upgrade "${SERVICE}" charts/ballast-service \
  --namespace ballast \
  -f "deploy/services/${SERVICE}.values.yaml" \
  --set resources.limits.memory="${GOOD_MEM}" \
  --set service.version="0.2.1-fixed"

kubectl -n ballast rollout status deploy/"${SERVICE}" --timeout=120s || true
kubectl -n ballast get pods -l app="${SERVICE}"
echo "==> ${SERVICE} restored."
