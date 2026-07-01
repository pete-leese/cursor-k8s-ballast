#!/usr/bin/env bash
# Deploy the five interdependent services into the `ballast` namespace via Helm.
# Idempotent: re-running upgrades in place. Requires the cluster from
# scripts/setup-cluster.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

kubectl apply -f deploy/namespace.yaml

for svc in payments checkout orders notifications ledger; do
  echo "==> helm upgrade --install ${svc}"
  helm upgrade --install "${svc}" charts/ballast-service \
    --namespace ballast \
    -f "deploy/services/${svc}.values.yaml"
done

echo "==> Waiting for rollouts"
for svc in payments checkout orders notifications ledger; do
  kubectl -n ballast rollout status deploy/"${svc}" --timeout=120s || true
done

echo "==> Deployed. Current pods:"
kubectl -n ballast get pods -o wide
