# cursor-k8s-ballast

A Cursor-driven **Root Cause Analysis** demo for **GitOps / Kubernetes** incidents.

`k8s-ballast` seeds a kind cluster with **Helm charts + ArgoCD manifests** for
five interdependent services, then deliberately ships a **bad chart bump**
(memory limit set too low) so the `payments` service OOM-kills on startup and
enters **CrashLoopBackOff**. A Cloud Agent (or the bundled deterministic engine)
investigates over a read-only **Prometheus/Grafana MCP** server: it correlates
the **rollout timestamp** with the **alert** firing time, characterises the
offending resource change, uses `topology.yaml` for **blast radius**, and
recommends **rollback vs forward-fix** as a strict, validated **RCA**.

This is the same "brief-in / contract-out" pattern as
[`cursor-causa`](https://github.com/pablogd-hashi/cursor-causa), reused in a
different customer environment (Kubernetes/GitOps instead of an app code path) —
which is exactly the pattern reuse an FDE needs to prove.

## What's here

| Path | What it is |
|---|---|
| `topology.yaml` | Declared service dependency graph (blast radius). |
| `charts/ballast-service/` | Reusable Helm chart; a service that allocates a memory ballast and is sensitive to its limit. |
| `deploy/services/*.values.yaml` | Per-service Helm values (the five services). |
| `deploy/argocd/` | ArgoCD `AppProject` + one `Application` per service (the GitOps representation). |
| `clusters/` | kind cluster config + kube-prometheus-stack values. |
| `observability/prometheus-rule.yaml` | `BallastServiceCrashLooping` / `...OOMKilled` alerts. |
| `ballast/contract.py` | The RCA contract (Pydantic v2). The trust boundary. |
| `schema/rca.schema.json` | JSON Schema generated from the contract; handed to the agent. |
| `ballast/engine.py` | Deterministic RCA engine (rollout↔alert correlation, blast radius, recommendation). |
| `ballast/sources.py` | Read-only Prometheus (HTTP) + Kubernetes (`kubectl`) triage sources. |
| `ballast/mcp_server.py` | Read-only MCP tools a Cursor agent calls to investigate. |
| `fixtures/rca_payments.json` | A valid, realistic RCA (feeds the mock investigator). |
| `scripts/` | `setup-cluster.sh`, `deploy.sh`, `break.sh`, `fix.sh`. |
| `architecture.md` | Division of labour, seams, deferred scope. |
| `docs/incident-runbook.md` | The narrated end-to-end incident walkthrough. |

## Quick start

Requires `docker`, `kind`, `kubectl`, `helm`, `python3` (and optionally
[`task`](https://taskfile.dev)).

```bash
task setup            # python venv + engine deps
task cluster:up       # kind + kube-prometheus-stack + ArgoCD
task deploy           # the five services via Helm
task break            # ship the bad chart bump -> payments CrashLoopBackOff

# In another shell, expose Prometheus, then run the RCA:
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090 &
task rca              # correlate rollout+alert+topology -> validated RCA

task fix              # forward-fix: restore the memory limit
```

No cluster? The engine still runs offline against the fixture:

```bash
task rca:mock
```

## The RCA at a glance

The engine emits JSON validated against `ballast/contract.py`. The headline for
the seeded incident:

- **summary** — a chart bump lowered `payments` memory to `16Mi` (from `128Mi`),
  OOM-killing the container on startup.
- **rollout_correlation** — alert fired N seconds after the rollout, inside the
  correlation window → correlated.
- **blast_radius** — `checkout, ledger, notifications, orders` depend on
  `payments` (from `topology.yaml`).
- **recommended_action** — `forward_fix`: restore the one memory-limit field
  rather than a full rollback that would re-roll `payments` and disrupt five
  dependents.

## Live Cursor Cloud Agent

The MCP server (`.cursor/mcp.json`) exposes read-only `get_firing_alerts`,
`query_prometheus`, `rollout_status`, `blast_radius`, and `run_rca` tools. A
Cloud Agent uses these to reproduce the RCA against the same contract. See
`docs/agent-mcp.md`.
