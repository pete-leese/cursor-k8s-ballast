#!/usr/bin/env bash
# Register the k8s-ballast AppProject and the app-of-apps root Application, so
# ArgoCD takes ownership of the cluster state and syncs the five services from
# git. Idempotent. Requires ArgoCD installed (scripts/setup-cluster.sh).
#
# If the repo is private, register credentials first, e.g.:
#   argocd repo add https://github.com/pete-leese/cursor-k8s-ballast \
#     --username <user> --password <token>
# (or create a repo-creds Secret). Public repos need nothing.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Applying AppProject + root app-of-apps"
kubectl apply -f deploy/argocd/project.yaml
kubectl apply -f deploy/argocd/root-app.yaml

echo "==> ArgoCD will now sync the child apps. Watch with:"
echo "    kubectl -n argocd get applications"
echo "    kubectl -n ballast get pods -w"
echo
echo "==> ArgoCD admin password:"
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "(secret not found yet)"
echo
echo "==> UI: kubectl -n argocd port-forward svc/argocd-server 8080:443  (user: admin)"
