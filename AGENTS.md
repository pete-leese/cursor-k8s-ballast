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

- `docker`, `kind`, `kubectl`, `helm` (and `task`) are installed in the VM
  image, not by the update script. The **update script only refreshes codebase
  deps** (creates `.venv` and `pip install -r requirements.txt`). Do not put
  cluster creation, `docker compose`, or service startup in it.
- The Python engine runs from the repo-root venv: `.venv/bin/python -m ballast...`.

### Bringing the platform up (per session)

The Docker daemon is **not auto-started** and the kind cluster does **not**
survive a fresh VM, so both are per-session startup steps (not update-script
material):

1. Start Docker once: run `sudo dockerd` in a background/tmux session (it stays
   in the foreground). Verify with `sudo docker info`. `docker` without `sudo`
   needs a fresh login shell for the `docker` group to apply; `sudo docker ...`
   and the `kind`/`kubectl`/`helm` tools (which read `~/.kube/config`) always work.
2. `./scripts/setup-cluster.sh` — creates the kind cluster, installs
   kube-prometheus-stack (namespace `monitoring`) and ArgoCD (namespace
   `argocd`). `SKIP_ARGOCD=1` skips ArgoCD if you only need the RCA loop.
   Container images are cached on disk, so re-creation after the first run is
   fast.
3. `./scripts/deploy.sh` — Helm-installs the five services into namespace
   `ballast`.

### Inducing and investigating the incident

- `./scripts/break.sh` ships the bad bump (`payments` memory `128Mi -> 16Mi`).
  `payments` OOM-kills on startup (exit 137) and enters CrashLoopBackOff; the
  `BallastServiceCrashLooping` alert fires after `for: 1m`, so allow ~1-2 min.
- Prometheus/Grafana are ClusterIP; reach the HTTP API via
  `kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090`
  (Grafana: `svc/kube-prometheus-stack-grafana 3000`, anonymous Viewer).
- Run the RCA: `.venv/bin/python -m ballast.cli investigate --service payments
  --healthy-memory 128Mi` (or `task rca`). `--mock` / `task rca:mock` replays the
  fixture with no cluster.
- `./scripts/fix.sh` restores the healthy limit (the forward-fix).

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
