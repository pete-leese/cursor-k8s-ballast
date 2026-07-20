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
| `scripts/` | `setup-cluster.sh`, `deploy.sh`, `port-forward.sh`, `demo.sh`, `run-console.sh`, `break.sh`, `fix.sh`, `grafana-token.sh`, `offline-rca-demo.sh`. |
| `architecture.md` | Division of labour, seams, deferred scope. |
| `docs/incident-runbook.md` | The narrated end-to-end incident walkthrough. |

## Prerequisites

The full demo runs on a **Mac (Apple Silicon) with Docker Desktop** — the
in-cluster CrashLoopBackOff (`kind` + a real kubelet OOM-kill) needs a normal
Docker/Kubernetes host. On macOS most tools install via [Homebrew](https://brew.sh):

| Tool | Why | Install (macOS) |
|---|---|---|
| **Docker Desktop** | Runs the `kind` node containers. Apple Silicon is the tested target. | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) |
| **kind** | The local Kubernetes cluster. | `brew install kind` |
| **kubectl** | Talk to the cluster / port-forward. | `brew install kubectl` |
| **helm** | Installs kube-prometheus-stack. | `brew install helm` |
| **task** ([go-task](https://taskfile.dev)) | Runs the workflows in `Taskfile.yml`. | `brew install go-task/tap/go-task` |
| **Python 3.11+** | The `ballast/` RCA engine + console (repo containers use 3.12). | ships with macOS / `brew install python@3.12` |
| **gh** (GitHub CLI) | `task break` / `task fix` open PRs via `gh`. Run `gh auth login` once. | `brew install gh` |
| **Node.js 18+** | `sdk-runner/` (`@cursor/sdk`) for a live Cursor Cloud Agent. | `brew install node` |
| **kubeconform** | Optional — offline chart/manifest validation (see `AGENTS.md`). | `brew install kubeconform` |

For a **live Cursor Cloud Agent** investigation you also need a **Cursor paid
plan**, a `CURSOR_API_KEY`, and the **Cursor GitHub app authorised** on your fork
of the repo (so the agent can clone it and open PRs).

> ArgoCD tracks `main` by default, so push/merge changes to `main` (or point
> `targetRevision` in `deploy/argocd/*.yaml` at your branch). Set
> `CURSOR_TARGET_REPO` in `.env` to your fork.

## Setup

```bash
git clone https://github.com/pete-leese/cursor-k8s-ballast
cd cursor-k8s-ballast

task setup                 # create .venv and install the RCA engine + console deps
cp .env.example .env       # then edit .env (at minimum set CURSOR_API_KEY for the demo)

task setup:playwright      # optional: Chromium for ArgoCD/Prometheus/Grafana evidence screenshots
(cd sdk-runner && npm install)   # optional: only for live Cursor Cloud Agents
```

`task setup` creates the repo-root virtualenv (`.venv/`); everything Python runs
from it (`.venv/bin/python -m ballast...`). See
[Environment variables](#environment-variables) for what to put in `.env`.

## Quickstart demo

Four steps (`task demo` runs the console wired to a **live Cursor Cloud Agent**,
so `CURSOR_API_KEY` must be set in `.env`):

```bash
task cluster:up          # 1. kind + kube-prometheus-stack + ArgoCD + sync the 5 services
task cluster:forward:bg  # 2. background port-forwards for Grafana/Prometheus/Alertmanager/ArgoCD
task demo                # 3. Ballast API (:8000) + console (:8501), manual investigations by default
task break               # 4. open the incident PR on main; merge it -> ArgoCD syncs the bad limit
```

What each command does and the URLs it exposes:

| Command | What it does | URLs |
|---|---|---|
| `task cluster:up` | Creates the `ballast` kind cluster, installs the monitoring stack + ArgoCD, and syncs the five services. Idempotent. | — |
| `task cluster:forward:bg` | Port-forwards the platform UIs in the background (stop with `task cluster:forward:stop`; use `task cluster:forward` to run in the foreground). | Prometheus `:9090`, Grafana `:3000` (`admin`/`admin`), Alertmanager `:9093`, ArgoCD `https://localhost:8080` (`admin` / from `argocd-initial-admin-secret`) |
| `task demo` | Starts the Ballast API and Streamlit console in **live Cursor Cloud Agent** mode (`BALLAST_INVESTIGATOR=cursor`). Investigations are manual (button-triggered) by default; run `BALLAST_ALERT_WATCH=1 task demo` to auto-investigate when the alert fires. Needs Prometheus reachable (step 2). | API `http://localhost:8000`, console `http://localhost:8501` |
| `task break` | Opens the incident PR (see below). | — |

Run `task cluster:info` at any time to reprint the URLs and credentials, or
`task` (no args) to list every available task.

## Inducing and resolving the incident

**Induce** — `task break` branches from `main`, lowers `ingest`'s memory limit
to `16Mi` in `deploy/services/ingest.values.yaml`, and opens a PR via `gh`. Merge
it: ArgoCD syncs the change, the kubelet OOM-kills `ingest` (exit 137) into
**CrashLoopBackOff**, and `StreamIngestCrashLooping` fires after ~1 minute.

```bash
kubectl -n demo get pods -l app=ingest -w        # watch it crash-loop
open http://localhost:9090/alerts?state=firing   # watch the alert fire
```

**Resolve** — investigate from the console, which recommends a **forward-fix**
(restore the one memory-limit field). Two ways to apply it:

- **Cloud Agent PR** — with `CURSOR_API_KEY` set (and auto-remediate on by
  default in the console when a key is present), the Cursor agent opens a PR that
  restores `ingest` memory. Review and merge; ArgoCD syncs the healthy value.
- **`task fix`** — opens the equivalent forward-fix PR (restore `128Mi`) directly
  via `gh`. Merge it and ArgoCD syncs.

## Teardown

```bash
task clean               # delete the kind cluster
```

Stop background port-forwards first with `task cluster:forward:stop` if they are
still running.

## Troubleshooting

- **`Prometheus not reachable` / `task demo` exits** — start the port-forwards
  first (`task cluster:forward:bg`); the console needs Prometheus on `:9090`.
- **`task break` / `task fix` fail** — install and authenticate the GitHub CLI
  (`gh auth login`), and make sure the current branch has a remote to push to.
- **Docker not running** — start Docker Desktop before `task cluster:up`;
  `kind` needs the daemon.
- **Cloud Agent can't see live metrics** — a **cloud** run investigates from the
  brief + repo and cannot reach your Mac's `localhost` Prometheus/Grafana. Set
  `CURSOR_RUNTIME=local` to run on your machine with local MCP access.
- **Nested-cluster note** — the caveat in `AGENTS.md` about not running a cluster
  is specific to the Cursor **Cloud VM**; the local Mac path above works normally.

## Environment variables

Nothing in `.env` is required for the local deterministic engine, but the demo's
live Cursor Cloud Agent and the Grafana MCP need a few. Copy the template and
edit it: `cp .env.example .env`. Values are read from `.env` (via
`scripts/run-console.sh`) and the process environment.

| Variable | Purpose | Default | Required? |
|---|---|---|---|
| `CURSOR_API_KEY` | Auth for the live Cursor Cloud Agent investigation and Cloud Agent remediation PRs. | _(empty)_ | Required for `task demo` / cursor mode |
| `CURSOR_RUNTIME` | `cloud` runs the agent in Cursor's cloud (can't reach your Mac's localhost); `local` runs it on this machine so it can use local Prometheus/Grafana MCP. | `cloud` | Optional |
| `CURSOR_TARGET_REPO` | Repo the Cloud Agent clones. Point at your fork. | this repo | Optional |
| `CURSOR_TARGET_REF` | Git ref the agent works from. | `main` | Optional |
| `CURSOR_MODEL` | Model the Cloud Agent uses. | `composer-2.5` | Optional |
| `BALLAST_INVESTIGATOR` | Investigator backend: `engine` (deterministic), `mock` (replay fixture), or `cursor` (live Cloud Agent). `task demo` sets `cursor`. | `engine` | Optional |
| `BALLAST_ALERT_WATCH` | `1` auto-starts an investigation when `StreamIngestCrashLooping` fires; `0` keeps investigations manual (button-triggered). | `0` | Optional |
| `BALLAST_AUTO_REMEDIATE` | `1` lets the console open a remediation PR automatically. The console defaults this to `1` when `CURSOR_API_KEY` is set. | `0` (auto `1` if key set) | Optional |
| `BALLAST_API_URL` | Where the console reaches the Ballast API. | `http://localhost:8000` | Optional |
| `BALLAST_HEALTHY_MEMORY` | The healthy memory limit the RCA restores. | `128Mi` | Optional |
| `PROMETHEUS_URL` | Prometheus HTTP API (after port-forward). | `http://localhost:9090` | Optional |
| `GRAFANA_URL` | Grafana base URL for the MCP / evidence screenshots. | `http://localhost:3000` | Optional |
| `GRAFANA_SERVICE_ACCOUNT_TOKEN` | Viewer token for the read-only `mcp-grafana` server. Mint one with `./scripts/grafana-token.sh` (Grafana port-forwarded). | _(empty)_ | Optional |
| `GRAFANA_DASHBOARD_UID` | UID of the provisioned Ballast RCA dashboard. | `ballast-rca` | Optional |
| `GH_TOKEN` / `GITHUB_TOKEN` | Fallback GitHub token for remediation PRs when the macOS keyring isn't available to the API process (classic PAT with `repo` scope). | _(empty)_ | Optional |
| `ARGOCD_PORT` / `ARGOCD_APP_NAMESPACE` / `ARGOCD_PROJECT` | ArgoCD UI port and namespace/project used for evidence screenshots and access info. | `8080` / `argocd` / `k8s-ballast` | Optional |
| `BALLAST_ARGOCD_SCREENSHOT` / `BALLAST_PROMETHEUS_SCREENSHOT` / `BALLAST_GRAFANA_SCREENSHOT` | Evidence-screenshot mode (`auto`\|`live`\|`snapshot`\|`off`); needs `task setup:playwright`. | `auto` | Optional |

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
  `./scripts/grafana-token.sh` (port-forward Grafana first) and put it in `.env`.

A live investigation runs through `sdk-runner/` (Node `@cursor/sdk`):

```bash
export CURSOR_API_KEY=...        # cursor.com -> Integrations -> API Keys
(cd sdk-runner && npm install && node smoke-test.mjs)  # cloud agent clones the repo, returns an RCA
```

A **cloud** agent runs in Cursor's cloud and cannot reach your Mac's `localhost`
Prometheus/Grafana — it investigates from the brief + the repo (charts,
`topology.yaml`, git history). Set `CURSOR_RUNTIME=local` to let the agent use
the local Grafana/Prometheus MCP directly. See `docs/agent-mcp.md`.
