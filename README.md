# cursor-k8s-ballast

A Cursor-driven **Root Cause Analysis** demo for **GitOps / Kubernetes**
incidents on a **media-streaming fleet**.

`k8s-ballast` seeds a kind cluster with **Helm charts + ArgoCD manifests** for
five interdependent stream services (`ingest` → `transcode` → `playback`, plus
`catalog` / `recommendations`), then deliberately ships a **bad chart bump**
(memory limit set too low) so **`ingest`** OOM-kills on startup and enters
**CrashLoopBackOff**. A Cloud Agent (or the bundled deterministic engine)
investigates over a read-only **Prometheus/Grafana MCP** server: it correlates
the **rollout timestamp** with the **alert** firing time, characterises the
offending resource change, uses `topology.yaml` for **blast radius**, and
recommends **rollback vs forward-fix** as a strict, validated **RCA**.

The console is a **fleet board / episode** war-room (not an app-latency triage
UI): dark rail, teal brand, Verdict + Signal trail, and autofix PRs through
ArgoCD GitOps.

## What's here

| Path | What it is |
|---|---|
| `topology.yaml` | Declared service dependency graph (blast radius). |
| `charts/ballast-service/` | Reusable Helm chart; a service that allocates a memory ballast and is sensitive to its limit. |
| `deploy/services/*.values.yaml` | Per-service Helm values (the five services). |
| `deploy/argocd/` | ArgoCD `AppProject`, `root-app` (app-of-apps), and `apps/` — one multi-source `Application` per service. Real GitOps. |
| `clusters/` | kind cluster config + kube-prometheus-stack values. |
| `observability/prometheus-rule.yaml` | `StreamIngestCrashLooping` / `...OOMKilled` alerts. |
| `ballast/contract.py` | The RCA contract (Pydantic v2). The trust boundary. |
| `schema/rca.schema.json` | JSON Schema generated from the contract; handed to the agent. |
| `ballast/engine.py` | Deterministic RCA engine (rollout↔alert correlation, blast radius, recommendation). |
| `ballast/sources.py` | Read-only Prometheus (HTTP) + Kubernetes (`kubectl`) triage sources. |
| `ballast/mcp_server.py` | Read-only MCP tools a Cursor agent calls to investigate. |
| `sdk-runner/` | Node `@cursor/sdk` runner for a live Cursor Cloud Agent investigation. |
| `fixtures/rca_ingest.json` | A valid, realistic RCA (feeds the mock investigator). |
| `scripts/` | `setup-cluster.sh`, `deploy.sh`, `argocd-bootstrap.sh`, `break.sh`, `fix.sh`, `grafana-token.sh`, `offline-rca-demo.sh`. |
| `architecture.md` | Division of labour, seams, deferred scope. |
| `docs/incident-runbook.md` | The narrated end-to-end incident walkthrough. |

## Quick start

Runs on a Mac (Apple Silicon) with **Docker Desktop** + `kind`, `kubectl`,
`helm`, `python3` (and optionally [`task`](https://taskfile.dev)). ArgoCD tracks
`main` by default, so push/merge your changes to `main` first (or point
`targetRevision` in `deploy/argocd/*.yaml` at your branch).

```bash
task setup            # python venv + engine deps
task cluster:up       # kind + kube-prometheus-stack + ArgoCD + sync the 5 services
task deploy           # re-run GitOps bootstrap only (idempotent)
task break            # open incident PR on main; merge when ready -> ArgoCD syncs

# In another shell, expose Prometheus, then run the RCA:
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090 &
task rca              # correlate rollout+alert+topology -> validated RCA

task fix              # open forward-fix PR on main
```

No cluster? Two offline paths (useful on hosts that can't run nested
Kubernetes — see `AGENTS.md`):

```bash
task rca:mock       # replay a fixture through the real contract validation
task rca:offline    # real Prometheus + kube-state-metrics stub: the
                    # StreamIngestCrashLooping alert fires and the engine
                    # produces a validated RCA from the live alert
```

## The RCA at a glance

The engine emits JSON validated against `ballast/contract.py`. The headline for
the seeded incident:

- **summary** — a chart bump lowered `ingest` memory to `16Mi` (from `128Mi`),
  OOM-killing the container on startup.
- **rollout_correlation** — alert fired N seconds after the rollout, inside the
  correlation window → correlated.
- **blast_radius** — `transcode, catalog, recommendations, playback` depend on
  `ingest` (from `topology.yaml`).
- **recommended_action** — `forward_fix`: restore the one memory-limit field
  rather than a full rollback that would re-roll `ingest` and disrupt five
  dependents.

## MCP + live Cursor Cloud Agent

Two MCP servers ship in `.mcp.json`:

- **`ballast`** (read-only) — `get_firing_alerts`, `query_prometheus`,
  `rollout_status`, `blast_radius`, `run_rca`.
- **`grafana`** — the official [`mcp-grafana`](https://github.com/grafana/mcp-grafana),
  read-only via a Viewer service-account token. Mint one with
  `task grafana:token` (port-forward Grafana first) and put it in `.env`.

A live investigation runs through `sdk-runner/` (Node `@cursor/sdk`):

```bash
export CURSOR_API_KEY=...        # cursor.com -> Integrations -> API Keys
task sdk:smoke                   # cloud agent clones the repo, returns an RCA
```

A **cloud** agent runs in Cursor's cloud and cannot reach your Mac's `localhost`
Prometheus/Grafana — it investigates from the brief + the repo (charts,
`topology.yaml`, git history). Set `CURSOR_RUNTIME=local` to let the agent use
the local Grafana/Prometheus MCP directly. See `docs/agent-mcp.md`.
