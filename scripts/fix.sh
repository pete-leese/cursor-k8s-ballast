#!/usr/bin/env bash
# Forward-fix the incident the GitOps way: commit a restore of the memory limit.
# ArgoCD syncs it and the service returns to Running/Ready. This is the action
# the RCA recommends (a targeted forward-fix, not a full rollback).
#
# Usage: ./scripts/fix.sh [SERVICE] [GOOD_MEMORY]
#   defaults: payments 128Mi
set -euo pipefail
cd "$(dirname "$0")/.."

SERVICE="${1:-payments}"
GOOD_MEM="${2:-128Mi}"
VALUES="deploy/services/${SERVICE}.values.yaml"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

echo "==> Restoring ${SERVICE} resources.limits.memory to ${GOOD_MEM} in ${VALUES}"
awk -v val="${GOOD_MEM}" '
  /^  limits:/ {inlim=1}
  inlim && /memory:/ {sub(/memory: *[0-9A-Za-z]+/, "memory: " val); inlim=0}
  {print}
' "${VALUES}" > "${VALUES}.tmp" && mv "${VALUES}.tmp" "${VALUES}"
grep -A3 '^  limits:' "${VALUES}"

echo "==> Committing + pushing the forward-fix to '${BRANCH}'"
git add "${VALUES}"
git commit -q -m "fix: restore ${SERVICE} memory limit to ${GOOD_MEM} (forward-fix)"
git push -q origin "${BRANCH}"

if command -v argocd >/dev/null 2>&1; then
  argocd app sync "${SERVICE}" >/dev/null 2>&1 || true
fi

echo "==> Forward-fix committed. ArgoCD will sync ${SERVICE} back to healthy."
echo "    kubectl -n ballast get pods -l app=${SERVICE} -w"
