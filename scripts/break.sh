#!/usr/bin/env bash
# Induce the demo incident the GitOps way:
#   1. Branch from main
#   2. Lower ingest memory limit (bad chart bump)
#   3. Open a demo PR (merge manually — ArgoCD syncs after merge to main)
#
# Usage: ./scripts/break.sh [SERVICE] [BAD_MEMORY]
#   defaults: ingest 16Mi
#
# Env:
#   BALLAST_AUTO_MERGE=1   optional: merge the PR automatically
#   BALLAST_BASE_BRANCH=main
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib/git-pr.sh
source "$(dirname "$0")/lib/git-pr.sh"

SERVICE="${1:-ingest}"
BAD_MEM="${2:-16Mi}"
BAD_REQ="${3:-${BAD_MEM}}"
VALUES="deploy/services/${SERVICE}.values.yaml"
BASE="$(git_pr_base_branch)"

git_pr_require_gh

echo "==> Creating incident branch from origin/${BASE}"
BRANCH="$(git_pr_create_branch "incident/break" "${SERVICE}")"
echo "    Branch: ${BRANCH}"

CURRENT="$(awk '/^  limits:/{l=1} l&&/memory:/{print $2; exit}' "${VALUES}")"
if [[ "${CURRENT}" == "${BAD_MEM}" ]]; then
  echo "ERROR: ${VALUES} is already ${BAD_MEM}." >&2
  echo "       Restore a healthy baseline first: task fix" >&2
  git checkout -q "${BASE}" 2>/dev/null || git checkout -q "origin/${BASE}"
  exit 1
fi

echo "==> Lowering ${SERVICE} memory: requests ${BAD_REQ}, limits ${BAD_MEM} (was limit ${CURRENT:-?})"
awk -v lim="${BAD_MEM}" -v req="${BAD_REQ}" '
  /^  requests:/ {inreq=1; inlim=0}
  /^  limits:/ {inlim=1; inreq=0}
  inreq && /memory:/ {sub(/memory: *[0-9A-Za-z]+/, "memory: " req); inreq=0}
  inlim && /memory:/ {sub(/memory: *[0-9A-Za-z]+/, "memory: " lim); inlim=0}
  {print}
' "${VALUES}" > "${VALUES}.tmp" && mv "${VALUES}.tmp" "${VALUES}"
grep -A6 '^resources:' "${VALUES}"

git_pr_commit_push "${BRANCH}" \
  "incident(${SERVICE}): lower memory limit to ${BAD_MEM}" \
  "${VALUES}"

PR_BODY="$(cat <<EOF
## Demo incident — \`${SERVICE}\`

Lowers \`resources.limits.memory\` to **${BAD_MEM}** and \`resources.requests.memory\` to **${BAD_REQ}** (limit was **${CURRENT:-unknown}**), below the ~40Mi startup ballast.

Requests must be ≤ limit or Kubernetes rejects the Deployment.

### Expected after merge
- ArgoCD syncs from \`${BASE}\`
- Kubelet OOM-kills the container (exit **137**)
- \`${SERVICE}\` enters **CrashLoopBackOff**
- \`StreamIngestCrashLooping\` fires after ~1 minute

### Restore
\`\`\`bash
task fix
task remediate:cursor
\`\`\`
EOF
)"

echo "==> Opening demo PR"
PR_URL="$(git_pr_open "${BRANCH}" \
  "incident(${SERVICE}): lower memory limit to ${BAD_MEM}" \
  "${PR_BODY}")"
echo "    ${PR_URL}"

git_pr_maybe_merge "${PR_URL}"

cat <<EOF

==> Next: merge the PR, then ArgoCD will sync ${SERVICE} from ${BASE}.
    Watch:  kubectl -n demo get pods -l app=${SERVICE} -w
            open http://localhost:9090/alerts?state=firing
    Restore: task fix
EOF
