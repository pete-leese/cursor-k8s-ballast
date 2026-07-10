#!/usr/bin/env bash
# Provision (or refresh) the Ballast RCA Grafana dashboard into the monitoring
# namespace. The kube-prometheus-stack Grafana sidecar watches ConfigMaps labelled
# grafana_dashboard=1 and loads the JSON automatically.
set -euo pipefail
cd "$(dirname "$0")/.."

NS="${GRAFANA_NAMESPACE:-monitoring}"
DASHBOARD="observability/grafana/ballast-rca-dashboard.json"
NAME="ballast-rca-dashboard"

if [[ ! -f "${DASHBOARD}" ]]; then
  echo "ERROR: missing ${DASHBOARD}" >&2
  exit 1
fi

if ! kubectl get ns "${NS}" >/dev/null 2>&1; then
  echo "ERROR: namespace ${NS} not found — run task cluster:up first" >&2
  exit 1
fi

echo "==> Applying Grafana dashboard ConfigMap ${NAME} in ${NS}"
# Build the ConfigMap from the JSON file, then stamp the sidecar label.
tmp="$(mktemp)"
trap 'rm -f "${tmp}"' EXIT
kubectl -n "${NS}" create configmap "${NAME}" \
  --from-file=ballast-rca-dashboard.json="${DASHBOARD}" \
  --dry-run=client -o yaml > "${tmp}"

# Inject labels without requiring yq.
awk '
  /^metadata:/ { print; print "  labels:"; print "    grafana_dashboard: \"1\""; print "    app.kubernetes.io/part-of: k8s-ballast"; next }
  { print }
' "${tmp}" | kubectl apply -f -

echo "==> Done. Sidecar usually reloads within ~60s."
echo "    URL: http://localhost:3000/d/ballast-rca?orgId=1&var-namespace=demo&var-container=ingest&from=now-30m&to=now"
echo "    (port-forward: task cluster:forward)"
