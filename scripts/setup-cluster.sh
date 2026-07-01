#!/usr/bin/env bash
# Create the local kind cluster and install the platform:
#   - kube-prometheus-stack (Prometheus + Grafana + Alertmanager + KSM)
#   - the BallastServiceCrashLooping alert rule
#   - ArgoCD (optional; SKIP_ARGOCD=1 to skip)
#
# Idempotent: safe to re-run. Requires docker, kind, kubectl, helm.
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER="${CLUSTER:-ballast}"

echo "==> Ensuring kind cluster '${CLUSTER}' exists"
if ! kind get clusters 2>/dev/null | grep -qx "${CLUSTER}"; then
  kind create cluster --config clusters/kind-config.yaml
else
  echo "    cluster already exists"
fi
kubectl cluster-info --context "kind-${CLUSTER}" >/dev/null

echo "==> Installing kube-prometheus-stack (namespace: monitoring)"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update prometheus-community >/dev/null
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  -f clusters/monitoring-values.yaml \
  --wait --timeout 10m

echo "==> Applying the CrashLoopBackOff alert rule"
kubectl apply -f observability/prometheus-rule.yaml

if [ "${SKIP_ARGOCD:-0}" != "1" ]; then
  echo "==> Installing ArgoCD (namespace: argocd)"
  kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
  echo "    waiting for argocd-server..."
  kubectl -n argocd rollout status deploy/argocd-server --timeout=5m || true
else
  echo "==> Skipping ArgoCD (SKIP_ARGOCD=1)"
fi

echo "==> Platform ready."
echo "    Deploy the services via GitOps:  ./scripts/deploy.sh"
echo "    (ArgoCD tracks 'main' by default — push/merge your changes there first,"
echo "     or edit targetRevision in deploy/argocd/*.yaml to your branch.)"
