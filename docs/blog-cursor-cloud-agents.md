# GitOps RCA with Cursor Cloud Agents on Kubernetes

*Meta description: A grounded walkthrough of how disciplined Helm + ArgoCD GitOps plus Cursor Cloud Agents turn a Kubernetes CrashLoopBackOff into a correlated root cause and a reviewable fix PR.*

**Tags:** `Cursor` · `Cursor Cloud Agents` · `Kubernetes` · `GitOps` · `ArgoCD` · `SRE` · `RCA`

---

## Kubernetes is hard to operate. Good practice makes it tractable.

Anyone who has carried a pager for a Kubernetes fleet knows the shape of a bad
night: a pod is flapping, an alert is screaming, a dashboard is red, and you are
three terminals deep trying to answer one question — *what changed, and is it
safe to undo?* Kubernetes gives you enormous power and, in return, an enormous
surface area to reason about.

The good news is that the demo repo this post is built on
([`cursor-k8s-ballast`](https://github.com/pete-leese/cursor-k8s-ballast))
starts from **disciplined practice**, not chaos. Workloads ship as **Helm
charts**. They are deployed via **GitOps with ArgoCD** using the **app-of-apps**
pattern, so the cluster's desired state is just a folder of manifests in git.
That discipline is what makes the hard part tractable: because every change is a
git commit that ArgoCD reconciles, an incident has a paper trail — and an AI
agent has something concrete to reason about.

This post is about the payoff of pairing that GitOps discipline with **Cursor**
and **Cursor Cloud Agents**: incidents get *detected* from correlated signals,
*root-caused* automatically, and *fixed* as a reviewable pull request that flows
right back through ArgoCD.

---

## What we deployed: five services, one chart, an app-of-apps

The lab models a **media-streaming fleet**. Five interdependent services run in
the `demo` namespace, confirmed live from the running console's cluster
overview:

- **`ingest`** — the memory-heavy upstream that buffers stream chunks. This is
  the primary/incident service.
- **`transcode`** — depends on `ingest`.
- **`playback`** — depends on `ingest` and `transcode`.
- **`recommendations`** — depends on `playback`.
- **`catalog`** — depends on `ingest`.

That dependency graph is declared in `topology.yaml`, and it is the source of
the RCA engine's blast-radius reasoning.

### One reusable Helm chart

Every service is the *same* Helm chart, `charts/ballast-service`, parameterised
per service. The chart is deliberately small and honest about the incident it is
designed to reproduce. From `charts/ballast-service/values.yaml`:

```yaml
# Megabytes of resident memory the app allocates and touches at startup.
ballastMb: 40

resources:
  requests:
    cpu: 25m
    memory: 64Mi
  limits:
    # The single field the "bad chart bump" lowers. 128Mi is healthy;
    # 16Mi OOM-kills the ~40Mi ballast on startup -> CrashLoopBackOff.
    cpu: 250m
    memory: 128Mi
```

The container allocates and touches ~40Mi of resident memory at startup (the
"ballast", passed through as the `BALLAST_MB` env var in the deployment
template). A key design choice: `fullnameOverride` pins the Deployment, the
`app=<service>` pod label, and the container name all to the service name, so the
alert, kube-state-metrics series (`container="<service>"`), and the engine's
`-l app=<service>` selectors line up.

### The app-of-apps GitOps layout

Deployment is pure GitOps. The structure under `deploy/argocd/` is:

- **`root-app.yaml`** — the single `Application` you bootstrap. It points at
  `deploy/argocd/apps` with `directory.recurse: true` and `syncPolicy.automated`
  (prune + selfHeal). Applying it once makes ArgoCD the owner of cluster state.
- **`apps/*.yaml`** — one child `Application` per service (`ingest`,
  `transcode`, `playback`, `recommendations`, `catalog`).
- **`deploy/services/*.values.yaml`** — the per-service Helm values.

Each child app is **multi-source**: one source provides the chart
(`charts/ballast-service`), another provides the per-service values file via the
`$values` ref. For `ingest`:

```yaml
sources:
  - repoURL: https://github.com/pete-leese/cursor-k8s-ballast
    targetRevision: main
    ref: values
  - repoURL: https://github.com/pete-leese/cursor-k8s-ballast
    targetRevision: main
    path: charts/ballast-service
    helm:
      releaseName: ingest
      valueFiles:
        - $values/deploy/services/ingest.values.yaml
```

That is the whole point: **the incident is a git edit to a values file**, and
ArgoCD syncs it. Nothing about the outage is out-of-band.

---

## The signals: a multi-signal correlation story

The most important feature of the RCA engine is that it does **not** trust a
single signal. Incident readiness is assessed across three independent sources
(`ballast/preflight.py`), and an incident is declared if *any* of them fires:

**1. Prometheus alerts.** A `PrometheusRule` (`observability/prometheus-rule.yaml`)
ships two alerts that watch kube-state-metrics:

- `StreamIngestCrashLooping` — fires when
  `kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} > 0` for
  `1m`.
- `StreamIngestOOMKilled` — fires on
  `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}`.

**2. Kubernetes API signals.** The engine reads live pod state directly: the
container's `waiting.reason` (`CrashLoopBackOff`), `lastState.terminated.reason`
(`OOMKilled`), `exitCode` (`137`), restart counts, ready/total pods, and the
live memory limit. Crucially, a CrashLoop/OOM straight from the API is enough to
start investigating *before* the Prometheus `for:` window even elapses.

**3. ArgoCD signals.** Application `sync_status` (`Synced` / `OutOfSync`) and
`health_status` (`Healthy` / `Degraded` / `Progressing` / `Missing`) are treated
as first-class incident evidence.

The console surfaces exactly this: each service row shows per-source signal chips
(Prometheus / Kubernetes / ArgoCD) that appear only when that signal is actually
firing.

### Correlating the bad bump with the alert

Here is the mechanism the engine roots out. A chart bump lowers `ingest`'s
`resources.limits.memory` from a healthy **128Mi** to **16Mi**. Because the
container touches ~40Mi at startup, the kubelet **OOM-kills** it (exit 137)
before it is ready → **CrashLoopBackOff** → the alert fires.

`ballast/engine.py` turns that into a strict, validated root cause
(`ballast/contract.py` is the trust boundary — a Pydantic v2 model that every
RCA must satisfy). The deterministic `analyze()` does five things:

1. **Reads the resource regression** — `resources.limits.memory: 128Mi → 16Mi`,
   noting it is the only field that changed.
2. **Correlates rollout ↔ symptom** — it compares the rollout timestamp (the
   current ReplicaSet's creation time, or an ArgoCD sync time) with the
   alert/symptom time. A delta inside the 600-second window is "correlated".
3. **Weighs agreement across signals** — Kubernetes CrashLoop/OOM, memory limit
   mismatch, Prometheus alert, ArgoCD Degraded. Confidence climbs with the number
   of agreeing signals (three-plus correlated signals → 0.95).
4. **Computes blast radius** from `topology.yaml` — the four services that depend
   on `ingest`.
5. **Recommends forward-fix vs rollback.** Because dependents exist, a full chart
   rollback would re-roll `ingest` and disrupt `transcode`, `playback`,
   `recommendations`, and `catalog`; restoring one field is lower-risk. The
   engine recommends **`forward_fix`**.

The same brief (`ballast/brief.py`) can be handed to three interchangeable
investigators behind that one contract (`ballast/investigator.py`): the
deterministic `engine`, a `mock` that replays a fixture, or — the interesting one
— a **Cursor Cloud Agent** that reads the brief and the read-only
Prometheus/Grafana MCP tools and returns JSON validated against the identical
contract.

![The Ballast console cluster overview: a red "Incident detected on ingest" banner sits above the Investigate button, with the five monitored services each showing per-source Prometheus, Kubernetes, and ArgoCD signal chips.](blog-assets/console-overview.png)
*The war-room view: the console has detected the incident on `ingest` from
correlated Prometheus, Kubernetes, and ArgoCD signals — one click from a full
investigation.*

---

## The centrepiece: the Cursor Cloud Agent remediation workflow

Detection and root cause are table stakes. What makes this loop *close* is the
Cursor Cloud Agent that remediates — and it does so in a GitOps-native way.

Once the RCA lands with a `forward_fix` (or `rollback`) recommendation,
`ballast/remediate.py` runs a three-step flow:

**Step 1 — File a GitHub issue.** The engine formats the RCA into a GitHub issue
via `gh issue create` — incident summary, rollout correlation, the exact resource
regression, and the recommended action.

**Step 2 — Launch a Cursor Cloud Agent via the SDK.** The remediator shells into
`sdk-runner/remediate.mjs`, which uses `@cursor/sdk`'s `Agent.create(...)` with a
`cloud` target:

```js
const agent = await Agent.create({
  apiKey,
  model: { id: model },
  cloud: {
    repos: [{ url: repoUrl, startingRef: ref }],
    autoCreatePR: true,
  },
});
const run = await agent.send(prompt);
```

The prompt hands the agent the incident ticket, the GitHub issue URL, and the
full RCA JSON, then asks it to restore `resources.limits.memory` in
`deploy/services/ingest.values.yaml`, open a titled PR against `main` that links
the issue, and **not merge it**.

This is the part worth emphasising: the agent **reasons about the remediation
itself** — it reads the values file, understands the regression from the RCA, and
writes the fix. It is not a canned `sed` script bolted onto a webhook.

**Step 3 — Open a forward-fix PR.** With `autoCreatePR: true`, the Cloud Agent
opens the PR. The Python side captures the PR URL from the SDK event stream (and,
as a fallback, discovers it from the issue's cross-reference timeline via
`gh api`), then watches for a human to merge it.

### Why running this as a *Cloud* Agent matters

- **Asynchronous.** The agent runs to completion on its own without holding the
  console hostage; the UI polls for the issue → PR transition and links the live
  run at `cursor.com/agents/<id>`.
- **Its own isolated environment.** A cloud VM clones the repo and works there —
  no mutation of your laptop or the cluster. (`run.mjs` notes the trade-off
  candidly: a cloud VM can't reach your Mac's localhost Prometheus/Grafana, so it
  investigates from the brief + repo; use `CURSOR_RUNTIME=local` when you want
  the agent to reach local MCP servers.)
- **GitOps-native.** The fix lands as a **reviewable PR**, not a live `kubectl`
  edit. A human reviews and merges; ArgoCD then syncs the healthy values from
  git. The remediation respects the exact same discipline that deployed the fleet
  in the first place.

Everything else in the system stays **read-only**: the Prometheus/Grafana MCP,
the Kubernetes source (`kubectl get` only), and the RCA engine never mutate the
cluster. The only things that change state are the human-run `break.sh` and the
Cloud Agent's remediation PR.

![The RCA verdict view in the Ballast console: a semicircular confidence gauge, the recommended action, an incident timeline correlating rollout with alert, and the auto-remediation section linking the GitHub issue and forward-fix PR.](blog-assets/console-verdict.png)
*The verdict: a confidence gauge, the `forward_fix` recommendation with the exact
remediation, the correlated incident timeline, and the auto-remediation panel
tracking the issue → PR handoff.*

---

## Evidence: a real incident, a real issue, a real PR

This is not a mock-up. Incident **INC-0057** ran this exact loop against the real
repo, and the Cursor Cloud Agent's output is on GitHub.

### The GitHub issue the RCA filed

[**Issue #115 — INC-0057: ingest OOM regression**](https://github.com/pete-leese/cursor-k8s-ballast/issues/115)
opens with the machine-generated root cause:

> Git commit be404b0 lowered ingest's resources.limits.memory to 16Mi (from
> 128Mi), below the 40Mi startup ballast; the kubelet OOM-kills the container
> (exit 137) and pods remain in CrashLoopBackOff with 121 restarts.
> StreamIngestCrashLooping is still firing; ArgoCD reports Degraded while synced.
>
> **Confidence:** 90% — 4 independent signals agree: Kubernetes CrashLoop/OOM,
> memory limit 16Mi!=128Mi, Prometheus alert, ArgoCD Degraded.

Note the honesty of the correlation: in this long-lived incident the alert's
`activeAt` was *outside* the 600s window, so the engine explicitly reports "not
correlated" on the raw timestamp and instead leans on the four agreeing signals
and the git regression for its causal link. That is the multi-signal design
paying off — it does not fabricate a tidy correlation it cannot support.

### The forward-fix PR the Cloud Agent opened

[**PR #116 — INC-0057: fix(ingest): restore memory limit to 128Mi**](https://github.com/pete-leese/cursor-k8s-ballast/pull/116)
links the issue and explains the change in the agent's own words:

> Commit `be404b0` lowered `resources.limits.memory` from **128Mi** to **16Mi**
> (and requests from 64Mi to 16Mi) in `deploy/services/ingest.values.yaml`. …
>
> **Why forward-fix (not rollback):** The regression is a single field change.
> Restoring the memory limit is low-risk and avoids a full chart rollback that
> would re-roll `ingest` and briefly disrupt four downstream services that depend
> on it: **catalog**, **playback**, **recommendations**, and **transcode**.
>
> **Change:** `resources.limits.memory`: 16Mi → **128Mi**;
> `resources.requests.memory`: 16Mi → **64Mi**.

The PR carries the "Open in Cursor" badge linking back to the cloud run that
produced it. A reviewer merges it to `main`; ArgoCD syncs the healthy limits and
the incident clears — the loop closes exactly where it started, in git.

> **A note on evidence screenshots.** The console can also attach per-incident
> ArgoCD / Grafana / Prometheus screenshots (`argocd.png`, `grafana.png`,
> `prometheus.png`) under `.ballast/artifacts/<INC>/`. At the time of writing the
> cluster was healthy and that directory was empty, so none are embedded here to
> avoid broken links; the two console captures above show the same signals live.

---

## The closed loop

Kubernetes is hard to operate — but disciplined GitOps plus Cursor Cloud Agents
make an incident a bounded, reviewable, repeatable event rather than a 2 a.m.
guessing game:

- **Detected** from *correlated* signals — Prometheus alerts, Kubernetes pod
  state, and ArgoCD health, never one source alone.
- **Root-caused** automatically into a strict, contract-validated RCA that
  correlates the bad Helm bump with the symptom and reasons about blast radius.
- **Fixed** by a Cursor Cloud Agent that reasons about the remediation and opens
  a **reviewable PR** — which a human merges and ArgoCD syncs back into the
  fleet.

The chart deployed the fleet through git; the fix returns through git. Cursor
sits in the middle as the investigator and the remediator, and the whole cluster
stays read-only the entire time.

### Try it

Clone [`cursor-k8s-ballast`](https://github.com/pete-leese/cursor-k8s-ballast),
run `task setup` and `task cluster:up` to stand up kind + ArgoCD + the five
services, then `task break` to open the incident PR. Point a `CURSOR_API_KEY` at
the SDK runner (`task sdk:smoke`) and watch a Cloud Agent investigate — or use the
console's **Investigate** button to run the loop end to end. The full narrated
walkthrough lives in `docs/incident-runbook.md`.
