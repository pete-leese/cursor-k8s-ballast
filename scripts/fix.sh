#!/usr/bin/env bash
# Forward-fix via PR on main (merge manually unless BALLAST_AUTO_MERGE=1).
#
# Usage: ./scripts/fix.sh [SERVICE] [GOOD_MEMORY]
#   defaults: ingest 128Mi
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib/git-pr.sh
source "$(dirname "$0")/lib/git-pr.sh"

SERVICE="${1:-ingest}"
GOOD_MEM="${2:-128Mi}"
GOOD_REQ="${3:-64Mi}"
VALUES="deploy/services/${SERVICE}.values.yaml"
BASE="$(git_pr_base_branch)"

git_pr_require_gh

echo "==> Creating forward-fix branch from origin/${BASE}"
BRANCH="$(git_pr_create_branch "incident/fix" "${SERVICE}")"
echo "    Branch: ${BRANCH}"

CURRENT="$(awk '/^  limits:/{l=1} l&&/memory:/{print $2; exit}' "${VALUES}")"
if [[ "${CURRENT}" == "${GOOD_MEM}" ]]; then
  echo "==> ${VALUES} is already ${GOOD_MEM} — nothing to fix."
  git checkout -q "${BASE}" 2>/dev/null || git checkout -q "origin/${BASE}"
  exit 0
fi

echo "==> Restoring ${SERVICE} memory: requests ${GOOD_REQ}, limits ${GOOD_MEM} (was limit ${CURRENT:-?})"
awk -v lim="${GOOD_MEM}" -v req="${GOOD_REQ}" '
  /^  requests:/ {inreq=1; inlim=0}
  /^  limits:/ {inlim=1; inreq=0}
  inreq && /memory:/ {sub(/memory: *[0-9A-Za-z]+/, "memory: " req); inreq=0}
  inlim && /memory:/ {sub(/memory: *[0-9A-Za-z]+/, "memory: " lim); inlim=0}
  {print}
' "${VALUES}" > "${VALUES}.tmp" && mv "${VALUES}.tmp" "${VALUES}"
grep -A6 '^resources:' "${VALUES}"

git_pr_commit_push "${BRANCH}" \
  "fix(${SERVICE}): restore memory limit to ${GOOD_MEM}" \
  "${VALUES}"

PR_BODY="$(cat <<EOF
## Forward-fix — \`${SERVICE}\`

Restores \`resources.limits.memory\` to **${GOOD_MEM}** and \`resources.requests.memory\` to **${GOOD_REQ}** (limit was **${CURRENT:-unknown}**).

Merge to \`${BASE}\` for ArgoCD to sync healthy limits.
EOF
)"

echo "==> Opening forward-fix PR"
PR_URL="$(git_pr_open "${BRANCH}" \
  "fix(${SERVICE}): restore memory limit to ${GOOD_MEM} (Ballast RCA)" \
  "${PR_BODY}")"
echo "    ${PR_URL}"

git_pr_maybe_merge "${PR_URL}"
