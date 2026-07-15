#!/usr/bin/env bash
# Print local URLs and default credentials for the ballast platform.
# Safe to re-run anytime (read-only).
set -euo pipefail

GRAFANA_PORT="${GRAFANA_PORT:-3000}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
ALERTMANAGER_PORT="${ALERTMANAGER_PORT:-9093}"
ARGOCD_PORT="${ARGOCD_PORT:-8080}"
GRAFANA_ADMIN="${GRAFANA_ADMIN:-admin}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-admin}"

argocd_password() {
  kubectl -n argocd get secret argocd-initial-admin-secret \
    -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || true
}

argocd_installed() {
  kubectl get ns argocd >/dev/null 2>&1 \
    && kubectl -n argocd get deploy argocd-server >/dev/null 2>&1
}

monitoring_installed() {
  kubectl get ns monitoring >/dev/null 2>&1 \
    && kubectl -n monitoring get svc kube-prometheus-stack-grafana >/dev/null 2>&1
}

ballast_deployed() {
  kubectl get ns demo >/dev/null 2>&1 \
    && kubectl -n demo get svc ingest >/dev/null 2>&1
}

echo
echo "==> Cluster access (port-forward first: task cluster:forward)"
echo
echo "  Monitoring"
if monitoring_installed; then
  echo "    Grafana        http://localhost:${GRAFANA_PORT}/"
  echo "                   login: ${GRAFANA_ADMIN} / ${GRAFANA_ADMIN_PASSWORD}"
  echo "                   anonymous Viewer also enabled (read-only, no login)"
  echo "    Prometheus     http://localhost:${PROMETHEUS_PORT}/"
  echo "                   alerts: http://localhost:${PROMETHEUS_PORT}/alerts"
  echo "    Alertmanager   http://localhost:${ALERTMANAGER_PORT}/"
else
  echo "    (not installed — run task cluster:up)"
fi
echo
echo "  GitOps"
if argocd_installed; then
  pw="$(argocd_password)"
  echo "    ArgoCD UI       https://localhost:${ARGOCD_PORT}/  (accept self-signed cert)"
  echo "                   login: admin / ${pw:-<password not ready yet>}"
else
  echo "    (not installed — run task cluster:up or SKIP_ARGOCD=1 to omit)"
fi
echo
echo "  Ballast services (after task deploy)"
if ballast_deployed; then
  echo "    In-cluster only by default (port 8080 per service):"
  for svc in ingest transcode playback catalog recommendations; do
    if kubectl -n demo get svc "$svc" >/dev/null 2>&1; then
      echo "      ${svc}  http://${svc}.demo.svc.cluster.local:8080/healthz"
    fi
  done
else
  echo "    (not deployed yet — run task deploy)"
fi
echo
echo "  Console (task console or task demo)"
echo "    Ballast API      http://localhost:8000/healthz"
echo "    Ballast console  http://localhost:8501/"
echo
echo "  Useful commands"
echo "    task demo                # console + manual investigations (BALLAST_ALERT_WATCH=1 to auto-investigate)"
echo "    task console             # API + console only"
echo "    task cluster:forward     # start all port-forwards (separate terminal)"
echo "    task rca               # RCA engine (needs Prometheus forward on ${PROMETHEUS_PORT})"
echo "    task grafana:token     # Viewer token for mcp-grafana (needs Grafana on ${GRAFANA_PORT})"
echo "    task deploy            # GitOps sync the five services via ArgoCD"
echo
