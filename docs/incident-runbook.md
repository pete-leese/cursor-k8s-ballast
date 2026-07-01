# Incident runbook — the seeded CrashLoopBackOff

The narrated end-to-end walkthrough. Assumes `task setup` and `task cluster:up`
have completed and the five services are deployed (`task deploy`).

## 1. Healthy baseline

```bash
kubectl -n ballast get pods
```

All five services (`payments`, `checkout`, `orders`, `notifications`, `ledger`)
are `Running` and `Ready`. `payments` is the upstream every other service
depends on (see `topology.yaml`).

## 2. Ship the bad chart bump

```bash
./scripts/break.sh            # payments resources.limits.memory: 128Mi -> 16Mi
```

This is a real `helm upgrade` that lowers `payments`' memory limit below its
~40 MiB startup ballast. The kubelet OOM-kills the container before it becomes
ready. Within a few restart cycles:

```bash
kubectl -n ballast get pods -l app=payments
# STATUS: CrashLoopBackOff, RESTARTS climbing
kubectl -n ballast describe pod -l app=payments | grep -A3 'Last State'
# Reason: OOMKilled, Exit Code: 137
```

## 3. The alert fires

`BallastServiceCrashLooping` fires after `for: 1m`. Expose Prometheus:

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090 &
open http://localhost:9090/alerts
```

## 4. Investigate — the RCA

```bash
.venv/bin/python -m ballast.cli investigate --service payments --healthy-memory 128Mi
```

The engine:

1. reads the firing alert and its `activeAt` from Prometheus;
2. reads the rollout timestamp (current ReplicaSet creation) and crash state
   (`OOMKilled` / `CrashLoopBackOff`, exit 137) from Kubernetes;
3. correlates the two — the alert fires seconds after the rollout → **correlated**;
4. computes blast radius from `topology.yaml` — `checkout, ledger, notifications, orders`;
5. recommends **forward_fix** (restore the one memory-limit field) over a full
   rollback that would re-roll `payments` and disrupt five dependents.

The output is JSON validated against `ballast/contract.py`.

## 5. Remediate

```bash
./scripts/fix.sh              # payments resources.limits.memory: -> 128Mi
kubectl -n ballast get pods -l app=payments   # back to Running/Ready
```

## Reset

```bash
task clean                    # kind delete cluster --name ballast
```
