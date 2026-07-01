# Investigating with a Cursor Cloud Agent (MCP)

The `ballast` MCP server (`ballast/mcp_server.py`, wired in `.cursor/mcp.json`)
exposes read-only triage + RCA tools so a Cursor Cloud Agent can investigate the
incident itself, producing an RCA against the same contract the engine uses.

## Tools

| Tool | Purpose |
|---|---|
| `list_services()` | Services in the declared topology. |
| `blast_radius(service)` | Transitive dependents of a service (rollback blast radius). |
| `get_firing_alerts()` | Currently firing Prometheus alerts (name, labels, `activeAt`). |
| `query_prometheus(promql)` | Run a read-only instant PromQL query. |
| `rollout_status(service)` | Rollout timestamp, memory limit, crash state. |
| `run_rca(service, healthy_memory)` | Full deterministic RCA (validated). |

All tools are read-only — nothing mutates the cluster.

## Prerequisites

- The cluster is up and the incident is induced (`./scripts/break.sh`).
- Prometheus is reachable at `PROMETHEUS_URL` (default `http://localhost:9090`);
  port-forward it: `kubectl -n monitoring port-forward
  svc/kube-prometheus-stack-prometheus 9090`.
- The venv exists (`.venv/bin/python`); the MCP command in `.cursor/mcp.json`
  uses it.

## A typical agent flow

1. `get_firing_alerts()` → sees `BallastServiceCrashLooping` for `payments`.
2. `rollout_status("payments")` → rollout timestamp + `OOMKilled` crash state.
3. `query_prometheus('kube_pod_container_status_waiting_reason{namespace="ballast",reason="CrashLoopBackOff"}')`
   → confirms the CrashLoopBackOff signal.
4. `blast_radius("payments")` → `checkout, ledger, notifications, orders`.
5. `run_rca("payments")` → a validated RCA recommending `forward_fix`.

The agent is a *codebase/infra investigator*, not a code generator: the product
is the RCA. The read-only Grafana MCP (`.mcp.json`) can be added for the same
role in a hosted Grafana.
