# Investigating with a Cursor Cloud Agent (MCP)

Two MCP servers ship in `.mcp.json`: the repo's own `ballast` server and the
official `mcp-grafana`. Together they let a Cursor agent investigate the incident
itself, producing an RCA against the same contract the engine uses.

## mcp-grafana (official, read-only)

Install `mcp-grafana` (`go install
github.com/grafana/mcp-grafana/cmd/mcp-grafana@latest`, or a release binary).
Give it a **Viewer** service-account token — the read-only guardrail:

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80 &
./scripts/grafana-token.sh    # prints GRAFANA_URL + GRAFANA_SERVICE_ACCOUNT_TOKEN
```

Put those in `.env`; `.mcp.json` passes them to `mcp-grafana`. Because a cloud
agent can't reach your Mac's localhost, `mcp-grafana` is primarily for the
**local in-IDE agent** (or a `CURSOR_RUNTIME=local` sdk-runner run).

## ballast MCP tools

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
