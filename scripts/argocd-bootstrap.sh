#!/usr/bin/env bash
# Register the k8s-ballast AppProject and the app-of-apps root Application, so
# ArgoCD takes ownership of the cluster state and syncs the five services from
# git. Idempotent. Requires ArgoCD installed (scripts/setup-cluster.sh).
#
# ArgoCD reads manifests from GitHub, not your working tree. By default we use
# the current git branch (must exist on origin). Override with:
#   ARGOCD_TARGET_REVISION=main ./scripts/argocd-bootstrap.sh
#
# If the repo is private, register credentials first, e.g.:
#   argocd repo add https://github.com/pete-leese/cursor-k8s-ballast \
#     --username <user> --password <token>
# (or create a repo-creds Secret). Public repos need nothing.
set -euo pipefail
cd "$(dirname "$0")/.."

ARGOCD_TARGET_REVISION="${ARGOCD_TARGET_REVISION:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"

apply_with_revision() {
  sed "s#targetRevision: main#targetRevision: ${ARGOCD_TARGET_REVISION}#g" "$1" | kubectl apply -f -
}

echo "==> Applying AppProject + app-of-apps (targetRevision: ${ARGOCD_TARGET_REVISION})"
kubectl apply -f deploy/argocd/project.yaml
apply_with_revision deploy/argocd/root-app.yaml
for app in deploy/argocd/apps/*.yaml; do
  apply_with_revision "$app"
done

echo "==> ArgoCD will now sync the child apps. Watch with:"
echo "    kubectl -n argocd get applications"
echo "    kubectl -n demo get pods -w"
echo
if [ "${ARGOCD_TARGET_REVISION}" != "main" ]; then
  echo "==> Note: tracking branch '${ARGOCD_TARGET_REVISION}' (not main)."
  echo "    Merge to main or set ARGOCD_TARGET_REVISION=main for production GitOps."
  echo
fi
echo "==> ArgoCD admin password:"
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "(secret not found yet)"
echo
echo "==> UI: task cluster:forward  (https://localhost:8080, user: admin)"
