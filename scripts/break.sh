#!/usr/bin/env bash
# Induce the incident: ship a bad chart bump that lowers the payments memory
# limit below its ballast working set. The rollout OOM-kills the container on
# startup and payments enters CrashLoopBackOff, firing BallastServiceCrashLooping
# within ~1-2 minutes. Reversible with scripts/fix.sh.
#
# Usage: ./scripts/break.sh [SERVICE] [BAD_MEMORY]
#   defaults: payments 16Mi
set -euo pipefail
cd "$(dirname "$0")/.."

SERVICE="${1:-payments}"
BAD_MEM="${2:-16Mi}"

echo "==> Shipping bad chart bump: ${SERVICE} resources.limits.memory=${BAD_MEM}"
helm upgrade "${SERVICE}" charts/ballast-service \
  --namespace ballast \
  -f "deploy/services/${SERVICE}.values.yaml" \
  --set resources.limits.memory="${BAD_MEM}" \
  --set service.version="0.2.0-badbump"

echo "==> Rollout shipped at $(date -u +%Y-%m-%dT%H:%M:%SZ). Watching pods..."
kubectl -n ballast rollout status deploy/"${SERVICE}" --timeout=30s || true
kubectl -n ballast get pods -l app="${SERVICE}"

cat <<EOF

==> Incident induced. ${SERVICE} will OOMKill -> CrashLoopBackOff.
    Give it ~1-2 min, then:
      kubectl -n ballast get pods -l app=${SERVICE}
      Alerts (port-forward):  kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090
                              http://localhost:9090/alerts
    Run the RCA once the alert is firing:
      .venv/bin/python -m ballast.cli investigate --service ${SERVICE} --healthy-memory 128Mi
    Restore health with:  ./scripts/fix.sh ${SERVICE}
EOF
