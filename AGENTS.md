# AGENTS.md

## Cursor Cloud specific instructions

`cursor-k8s-ballast` is a GitOps/Kubernetes RCA demo: Helm charts + ArgoCD
manifests for five interdependent services, a deliberately bad chart bump that
drives `payments` into CrashLoopBackOff, and a Python RCA engine (`ballast/`)
that correlates the rollout timestamp with the alert and recommends rollback vs
forward-fix. Standard commands live in `README.md` and `Taskfile.yml`; the
end-to-end walkthrough is `docs/incident-runbook.md`. Only the non-obvious
startup caveats are captured here.

### Tooling / update script split

- `docker`, `kind`, `k3d`, `kubectl`, `helm`, `kubeconform` (and `task`) are
  installed in the VM image, not by the update script. The **update script only
  refreshes codebase deps** (creates `.venv` and `pip install -r
  requirements.txt`). Do not put cluster creation, `docker compose`, or service
  startup in it.
- The Python engine runs from the repo-root venv: `.venv/bin/python -m ballast...`.

### IMPORTANT: this Cloud VM cannot run a nested Kubernetes cluster

The VM's cgroup-v2 root is `domain threaded` and immutable (it is a namespaced
root controlled from outside; `echo domain > .../cgroup.type` → `Operation not
permitted`, and `+memory` in `cgroup.subtree_control` → `Operation not
supported`). Consequences, all verified during setup:

- **kind** fails: its systemd node cannot create `/init.scope`
  (`Failed to allocate manager object: Structure needs cleaning`).
- **k3d / k3s** fails: `failed to evacuate root cgroup: read
  /sys/fs/cgroup/cgroup.procs: operation not supported` (threaded cgroups expose
  `cgroup.threads`, not `cgroup.procs`).
- **Docker cannot enforce `--memory`** (`cannot enter cgroupv2 ... it is in
  threaded mode`), so the real kubelet OOM-kill cannot be reproduced here.

So the **live in-cluster CrashLoopBackOff demo (`setup-cluster.sh` → `deploy.sh`
→ `break.sh`) only runs on a normal Docker/Kubernetes host**, not in this Cloud
VM. Do not burn time retrying kind/k3s here. The scripts, charts, and ArgoCD
manifests are correct and validated (`helm lint`/`template`, `kubeconform`).

### Docker (per session)

The Docker daemon is **not auto-started**. `/etc/docker/daemon.json` is already
set to `fuse-overlayfs` + `"ip6tables": false` (the latter is required or Docker
networking fails with `ip6tables ... table 'raw' does not exist`). Start it once
per session: `sudo dockerd` in a background/tmux session. `docker` without
`sudo` needs a fresh login shell for the `docker` group (`sg docker -c '...'`
works); `sudo docker ...` always works.

### Verifying the project IN this VM (the offline path)

1. Charts/manifests: `helm lint charts/ballast-service` and, per service,
   `helm template ... | kubeconform -strict -ignore-missing-schemas`.
2. Workload: `docker run` the app from `charts/ballast-service/files/app.py`
   (`python:3.12-alpine`, mount at `/app/app.py`) and curl `/healthz` + `/metrics`.
3. RCA engine end-to-end against a **real** Prometheus:
   `task rca:offline` (or `./scripts/offline-rca-demo.sh`) stands up Prometheus +
   a kube-state-metrics stub, waits for `BallastServiceCrashLooping` to fire,
   then runs the engine against the live alert. `task rca:mock` replays the
   fixture through contract validation.
   - The engine's `--rollout-at`, `--current-memory`, `--simulate-oom` flags feed
     the rollout/crash facts a live cluster would provide; they exist for exactly
     this no-cluster case and are explicit overrides, never silent defaults.

### On a real cluster (the user's Mac, Apple Silicon + Docker Desktop)

GitOps via ArgoCD is the deploy path:

- `./scripts/setup-cluster.sh` — kind (local Docker) + kube-prometheus-stack +
  ArgoCD. Images are multi-arch, so arm64 (Apple Silicon) works.
- `./scripts/deploy.sh` — applies the ArgoCD `AppProject` + `root-app`
  (app-of-apps in `deploy/argocd/`); ArgoCD then syncs the five services.
  **ArgoCD tracks `main`** (targetRevision), so the branch must be pushed/merged
  there, or edit `targetRevision` in `deploy/argocd/*.yaml`.
- `./scripts/break.sh` / `./scripts/fix.sh` are **git-commit driven**: they edit
  `deploy/services/payments.values.yaml` (`limits.memory` via `awk`, preserving
  the rest), commit, and push to the current branch; ArgoCD syncs the change.
  `break.sh` → `16Mi` → OOMKill → CrashLoopBackOff → `BallastServiceCrashLooping`
  after `for: 1m`; `fix.sh` → `128Mi`.
- `task rca` after `kubectl -n monitoring port-forward
  svc/kube-prometheus-stack-prometheus 9090`.
- `mcp-grafana` (in `.mcp.json`) needs a Viewer token: `task grafana:token`
  after `kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana
  3000:80`.
- Live Cloud Agent: `sdk-runner/` (`@cursor/sdk`) needs `CURSOR_API_KEY`, a
  Cursor paid plan, and the Cursor GitHub app authorised on the repo. A **cloud**
  run cannot reach the Mac's localhost Prometheus/Grafana (it works from the
  brief + repo); use `CURSOR_RUNTIME=local` for local MCP access.

### Non-obvious gotchas

- **Container name == service name by design.** The chart sets
  `fullnameOverride` so the Deployment, pod label `app=<svc>`, and container
  name all equal the service name. The RCA engine relies on this: it selects
  pods with `-l app=<svc>` and the alert / kube-state-metrics series carry
  `container="<svc>"`. Renaming would break the correlation.
- **The OOM is intentional.** `ballastMb: 40` (touched, so resident) exceeds the
  bad `16Mi` limit — that is what produces the CrashLoopBackOff. It is the demo's
  regression, not a broken environment. The healthy `128Mi` limit runs fine.
- **kube-prometheus-stack discovers all monitors/rules.** `monitoring-values.yaml`
  sets `serviceMonitorSelectorNilUsesHelmValues=false` (and the rule/pod/probe
  equivalents) so the per-service `ServiceMonitor`s and the
  `ballast-crashloop` `PrometheusRule` are scraped without extra release labels.
- **The RCA engine never mutates the cluster.** Only `break.sh` / `fix.sh` (Helm)
  change state. `ballast` triage and the MCP tools are read-only.
- **ArgoCD is the GitOps representation, not the live-demo driver.** The
  self-contained incident is induced via Helm (`break.sh`); ArgoCD Applications
  in `deploy/argocd/` show how the same chart would be synced from git in
  production. The rollout↔alert correlation is identical either way (it reads the
  Kubernetes ReplicaSet timestamp).
