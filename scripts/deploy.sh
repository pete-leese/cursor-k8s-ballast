#!/usr/bin/env bash
# Deploy the five interdependent services via ArgoCD (GitOps). This is a thin
# wrapper around the app-of-apps bootstrap; ArgoCD renders charts/ballast-service
# with each service's values file from git and reconciles the `demo` namespace.
#
# Requires the platform from scripts/setup-cluster.sh (kind + kube-prometheus-stack
# + ArgoCD) and that ArgoCD tracks the branch you pushed (default: main).
set -euo pipefail
cd "$(dirname "$0")/.."

./scripts/argocd-bootstrap.sh

echo "==> Waiting for the ballast namespace to appear and pods to schedule..."
for _ in $(seq 1 30); do
  kubectl get ns demo >/dev/null 2>&1 && break
  sleep 2
done
kubectl -n demo get pods 2>/dev/null || true
echo "==> ArgoCD is now reconciling. 'kubectl -n argocd get applications' shows sync status."
