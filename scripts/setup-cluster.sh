#!/usr/bin/env bash
# Create the local kind cluster and install the platform:
#   - kube-prometheus-stack (Prometheus + Grafana + Alertmanager + KSM)
#   - the BallastServiceCrashLooping alert rule
#   - ArgoCD (optional; SKIP_ARGOCD=1 to skip)
#   - app-of-apps bootstrap + five services (optional; SKIP_DEPLOY=1 to skip)
#
# Idempotent: safe to re-run. Requires docker, kind, kubectl, helm.
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER="${CLUSTER:-ballast}"
MONITORING_WAIT_TIMEOUT="${MONITORING_WAIT_TIMEOUT:-600}"

wait_for_monitoring_stack() {
  local timeout="$1"
  local deadline=$(( SECONDS + timeout ))
  local resources=(
    deployment/kube-prometheus-stack-operator
    deployment/kube-prometheus-stack-kube-state-metrics
    deployment/kube-prometheus-stack-grafana
    statefulset/prometheus-kube-prometheus-stack-prometheus
    statefulset/alertmanager-kube-prometheus-stack-alertmanager
  )

  remaining() {
    local left=$(( deadline - SECONDS ))
    echo $(( left > 0 ? left : 0 ))
  }

  echo "==> Waiting for monitoring stack to become ready (timeout: ${timeout}s)"
  for resource in "${resources[@]}"; do
    local left
    left="$(remaining)"
    if [ "$left" -le 0 ]; then
      echo "ERROR: timed out waiting for monitoring stack" >&2
      kubectl -n monitoring get pods -o wide
      return 1
    fi
    echo "    waiting for ${resource}..."
    if ! kubectl -n monitoring rollout status "${resource}" --timeout="${left}s"; then
      echo "ERROR: ${resource} did not become ready" >&2
      kubectl -n monitoring get pods -o wide
      return 1
    fi
  done

  echo "    verifying Prometheus CR is Available..."
  left="$(remaining)"
  if ! kubectl wait --for=condition=Available \
      prometheus/kube-prometheus-stack-prometheus -n monitoring \
      --timeout="${left}s"; then
    echo "ERROR: Prometheus CR not Available" >&2
    kubectl -n monitoring get prometheus,alertmanager,pods -o wide
    return 1
  fi

  echo "    verifying Grafana /api/health..."
  while [ "$(remaining)" -gt 0 ]; do
    if kubectl -n monitoring exec deploy/kube-prometheus-stack-grafana -c grafana \
        -- wget -qO- http://localhost:3000/api/health 2>/dev/null \
        | grep -qE '"database"[[:space:]]*:[[:space:]]*"ok"'; then
      echo "    monitoring stack ready"
      return 0
    fi
    sleep 3
  done

  echo "ERROR: Grafana /api/health did not pass" >&2
  kubectl -n monitoring get pods -o wide
  return 1
}

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
  --timeout 5m
wait_for_monitoring_stack "${MONITORING_WAIT_TIMEOUT}"

echo "==> Applying the CrashLoopBackOff alert rule"
kubectl apply -f observability/prometheus-rule.yaml

echo "==> Provisioning Ballast RCA Grafana dashboard"
./scripts/apply-grafana-dashboard.sh

if [ "${SKIP_ARGOCD:-0}" != "1" ]; then
  echo "==> Installing ArgoCD (namespace: argocd)"
  kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
  # Server-side apply avoids stuffing the full CRD into last-applied-configuration
  # (applicationsets.argoproj.io exceeds the 262144-byte annotation limit).
  kubectl apply --server-side --force-conflicts \
    -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
  echo "    waiting for argocd-server..."
  kubectl -n argocd rollout status deploy/argocd-server --timeout=5m || true
  if [ "${SKIP_DEPLOY:-0}" != "1" ]; then
    echo "==> Bootstrapping ArgoCD app-of-apps and syncing the five services"
    ./scripts/deploy.sh
  fi
else
  echo "==> Skipping ArgoCD (SKIP_ARGOCD=1)"
fi

echo "==> Platform ready."
./scripts/cluster-access-info.sh
