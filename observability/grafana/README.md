# Grafana — Ballast RCA dashboard

Dashboard JSON: [`ballast-rca-dashboard.json`](./ballast-rca-dashboard.json)

**UID:** `ballast-rca`  
**Title:** Ballast RCA — Kubernetes

## What it shows

Kube-state-metrics + cAdvisor panels used as RCA evidence screenshots:

| Panel | Metric / signal |
|---|---|
| CrashLoopBackOff | `kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"}` |
| OOMKilled | `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}` |
| Restarts | `kube_pod_container_status_restarts_total` |
| Ready / desired replicas | `kube_deployment_status_replicas_*` |
| Memory limit | `kube_pod_container_resource_limits{resource="memory"}` |
| Working set vs limit | `container_memory_working_set_bytes` vs limit |
| Waiting / terminated reasons | time series by `reason` |
| CPU | `container_cpu_usage_seconds_total` |

Variables: **namespace** (default `ballast`), **container** / service (default `payments`).

## Apply / refresh

```bash
./scripts/apply-grafana-dashboard.sh
# or after cluster setup — setup-cluster.sh applies it automatically
```

Open (with port-forward):

```text
http://localhost:3000/d/ballast-rca?orgId=1&var-namespace=ballast&var-container=payments&from=now-30m&to=now&kiosk
```

Ballast screenshot capture uses this UID by default (`GRAFANA_DASHBOARD_UID=ballast-rca`).
