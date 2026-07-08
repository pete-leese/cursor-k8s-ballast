#!/usr/bin/env bash
# Port-forward the platform UIs to localhost. Runs until Ctrl+C (or SIGTERM).
#
# Usage:
#   ./scripts/port-forward.sh           # foreground (default)
#   BACKGROUND=1 ./scripts/port-forward.sh   # detach; stop with task cluster:forward:stop
#
# Override local ports via GRAFANA_PORT, PROMETHEUS_PORT, ALERTMANAGER_PORT, ARGOCD_PORT.
set -euo pipefail
cd "$(dirname "$0")/.."

GRAFANA_PORT="${GRAFANA_PORT:-3000}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
ALERTMANAGER_PORT="${ALERTMANAGER_PORT:-9093}"
ARGOCD_PORT="${ARGOCD_PORT:-8080}"
PIDFILE="${PIDFILE:-${TASKFILE_DIR:-.}/.cluster-port-forwards.pid}"

pids=()

stop_forwards() {
  local pid
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  rm -f "$PIDFILE"
}

start_forward() {
  local label=$1
  shift
  if [ "${BACKGROUND:-0}" = "1" ]; then
    nohup kubectl "$@" >/dev/null 2>&1 &
    pids+=("$!")
    disown
  else
    kubectl "$@" &
    pids+=("$!")
  fi
  echo "    ${label}"
}

require_svc() {
  local ns=$1 svc=$2
  kubectl -n "$ns" get svc "$svc" >/dev/null 2>&1 || {
    echo "ERROR: service ${ns}/${svc} not found — run task cluster:up first" >&2
    exit 1
  }
}

echo "==> Starting port-forwards (Ctrl+C to stop)"
echo

if kubectl get ns monitoring >/dev/null 2>&1; then
  require_svc monitoring kube-prometheus-stack-grafana
  require_svc monitoring kube-prometheus-stack-prometheus
  require_svc monitoring kube-prometheus-stack-alertmanager
  start_forward "Grafana       http://localhost:${GRAFANA_PORT}/" \
    -n monitoring port-forward "svc/kube-prometheus-stack-grafana" "${GRAFANA_PORT}:80"
  start_forward "Prometheus    http://localhost:${PROMETHEUS_PORT}/" \
    -n monitoring port-forward "svc/kube-prometheus-stack-prometheus" "${PROMETHEUS_PORT}:9090"
  start_forward "Alertmanager  http://localhost:${ALERTMANAGER_PORT}/" \
    -n monitoring port-forward "svc/kube-prometheus-stack-alertmanager" "${ALERTMANAGER_PORT}:9093"
else
  echo "    monitoring namespace not found — skipping Grafana/Prometheus/Alertmanager"
fi

if kubectl -n argocd get svc argocd-server >/dev/null 2>&1; then
  start_forward "ArgoCD        https://localhost:${ARGOCD_PORT}/" \
    -n argocd port-forward "svc/argocd-server" "${ARGOCD_PORT}:443"
else
  echo "    argocd-server not found — skipping ArgoCD"
fi

echo
./scripts/cluster-access-info.sh

if [ "${BACKGROUND:-0}" = "1" ]; then
  printf '%s\n' "${pids[@]}" >"$PIDFILE"
  echo "==> Port-forwards running in background (PIDs in ${PIDFILE})"
  echo "    Stop with: task cluster:forward:stop"
  exit 0
fi

trap stop_forwards INT TERM
wait
