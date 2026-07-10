#!/usr/bin/env bash
# Deploy the five demo services via ArgoCD only (GitOps). Do not helm-install
# into `demo` by hand — that leaves sync status Unknown. This wraps
# argocd-bootstrap so ArgoCD owns the `demo` namespace.
#
# Requires the platform from scripts/setup-cluster.sh (kind + kube-prometheus-stack
# + ArgoCD). ArgoCD reads GitHub, so the branch must be pushed.
#   ARGOCD_TARGET_REVISION=<branch> ./scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

./scripts/argocd-bootstrap.sh

echo "==> Waiting for the demo namespace to appear and pods to schedule..."
for _ in $(seq 1 30); do
  kubectl get ns demo >/dev/null 2>&1 && break
  sleep 2
done
kubectl -n demo get pods 2>/dev/null || true
echo "==> ArgoCD is now reconciling. 'kubectl -n argocd get applications' shows sync status."
