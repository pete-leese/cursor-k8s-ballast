#!/usr/bin/env bash
# Induce the incident the GitOps way: commit a bad chart bump that lowers the
# payments memory limit below its ~40Mi startup ballast. ArgoCD syncs the commit,
# the rollout OOM-kills the container on startup, payments enters CrashLoopBackOff
# and BallastServiceCrashLooping fires (~1-2 min). Reversible with scripts/fix.sh.
#
# Usage: ./scripts/break.sh [SERVICE] [BAD_MEMORY]
#   defaults: payments 16Mi
#
# Note: ArgoCD tracks a branch (targetRevision, default `main`). This script
# commits to the CURRENT branch and pushes; make sure ArgoCD tracks it (or run
# this on main). Requires push access to the repo.
set -euo pipefail
cd "$(dirname "$0")/.."

SERVICE="${1:-payments}"
BAD_MEM="${2:-16Mi}"
VALUES="deploy/services/${SERVICE}.values.yaml"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

echo "==> Lowering ${SERVICE} resources.limits.memory to ${BAD_MEM} in ${VALUES}"
awk -v val="${BAD_MEM}" '
  /^  limits:/ {inlim=1}
  inlim && /memory:/ {sub(/memory: *[0-9A-Za-z]+/, "memory: " val); inlim=0}
  {print}
' "${VALUES}" > "${VALUES}.tmp" && mv "${VALUES}.tmp" "${VALUES}"
grep -A3 '^  limits:' "${VALUES}"

echo "==> Committing + pushing the bad bump to '${BRANCH}'"
git add "${VALUES}"
git commit -q -m "incident: lower ${SERVICE} memory limit to ${BAD_MEM} (bad chart bump)"
git push -q origin "${BRANCH}"

# Nudge ArgoCD if the CLI is available and logged in; otherwise auto-sync handles it.
if command -v argocd >/dev/null 2>&1; then
  argocd app sync "${SERVICE}" >/dev/null 2>&1 || true
fi

cat <<EOF

==> Bad bump committed at $(date -u +%Y-%m-%dT%H:%M:%SZ). ArgoCD will sync it.
    Watch:  kubectl -n argocd get applications
            kubectl -n ballast get pods -l app=${SERVICE} -w
    ${SERVICE} will OOMKill (exit 137) -> CrashLoopBackOff; BallastServiceCrashLooping
    fires after ~1 min. Then run the RCA:
      .venv/bin/python -m ballast.cli investigate --service ${SERVICE} --healthy-memory 128Mi
    Restore with:  ./scripts/fix.sh ${SERVICE}
EOF
