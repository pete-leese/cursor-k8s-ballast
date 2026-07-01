#!/usr/bin/env bash
# Offline end-to-end RCA demo for hosts that cannot run a nested Kubernetes
# cluster (e.g. the Cursor Cloud VM, whose cgroup-v2 root is `domain threaded`
# so kind/k3s and memory-limit OOM cannot run — see AGENTS.md).
#
# It stands up a real Prometheus + a kube-state-metrics stub in Docker, waits for
# the BallastServiceCrashLooping alert to fire, then runs the ballast RCA engine
# against that live Prometheus (supplying the rollout/crash facts a cluster would
# otherwise provide). Proves the Prometheus/alert integration, the rollout↔alert
# correlation, the topology blast radius, and the rollback-vs-forward-fix
# recommendation — all end-to-end.
#
# Requires: docker (daemon running), the venv (task setup). Uses `sg docker`-free
# docker; if your shell is not in the docker group, run under `sg docker -c`.
set -euo pipefail
cd "$(dirname "$0")/.."

HACK="$PWD/hack/offline"
PY="$PWD/.venv/bin/python"
NET=ballast-offline

echo "==> Starting Prometheus + kube-state-metrics stub"
docker network create "$NET" >/dev/null 2>&1 || true
docker rm -f ballast-ksm ballast-prom >/dev/null 2>&1 || true
docker run -d --name ballast-ksm --network "$NET" \
  -v "$HACK/kube-state-metrics.txt:/data/metrics:ro" -w /data \
  python:3.12-alpine python3 -m http.server 8081 >/dev/null
docker run -d --name ballast-prom --network "$NET" -p 9090:9090 \
  -v "$HACK/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  -v "$HACK/rules.yml:/etc/prometheus/rules.yml:ro" \
  prom/prometheus:v2.53.0 --config.file=/etc/prometheus/prometheus.yml >/dev/null

# "Rollout" happened just before the metrics went bad.
ROLLOUT_TS="$(date -u -d '-10 seconds' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "==> Waiting for BallastServiceCrashLooping to fire (for: 1m)..."
for _ in $(seq 1 40); do
  if curl -fsS http://localhost:9090/api/v1/alerts 2>/dev/null \
      | grep -q '"alertname":"BallastServiceCrashLooping","[^}]*"state":"firing"' \
     || curl -fsS http://localhost:9090/api/v1/alerts 2>/dev/null \
      | grep -q 'BallastServiceCrashLooping'; then
    state=$(curl -fsS http://localhost:9090/api/v1/alerts | "$PY" -c "import sys,json;a=[x for x in json.load(sys.stdin)['data']['alerts'] if x['labels']['alertname']=='BallastServiceCrashLooping'];print(a[0]['state'] if a else 'none')")
    [ "$state" = "firing" ] && break
  fi
  sleep 3
done

echo "==> Running the ballast RCA engine against live Prometheus"
"$PY" -m ballast.cli investigate \
  --service payments --healthy-memory 128Mi \
  --prometheus-url http://localhost:9090 \
  --no-cluster --rollout-at "$ROLLOUT_TS" --current-memory 16Mi --simulate-oom \
  --chart-version-from 0.1.0 --chart-version-to 0.2.0-badbump

cat <<EOF

==> Done. Prometheus UI: http://localhost:9090/alerts
    Tear down: docker rm -f ballast-ksm ballast-prom && docker network rm $NET
EOF
