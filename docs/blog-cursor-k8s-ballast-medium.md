# From CrashLoop to Fix PR: Investigating a Kubernetes Incident with Cursor

*How we used Cursor Cloud Agents, Bugbot, screenshots, and auto-remediation to turn a GitOps outage on a **media-streaming fleet** into a closed loop — triage → verdict → fix PR.*

---

**Subtitle / deck (optional):**  
A hands-on walkthrough of Cursor as an incident-response copilot for Kubernetes and ArgoCD — CrashLoopBackOff on stream **ingest**, not an app-latency fintech demo.

**Tags (Medium):** `Cursor` · `Kubernetes` · `GitOps` · `DevOps` · `AI Agents` · `SRE` · `Streaming`

**Canonical demo repo:** [cursor-k8s-ballast](https://github.com/pete-leese/cursor-k8s-ballast) *(update URL if needed)*

---

<!-- MEDIUM: Cover image — wide hero of the Ballast Fleet board -->
![Cover: Ballast console — fleet board](SCREENSHOT_PLACEHOLDER_cover_fleet_board.png)
*Caption: The Ballast console landing on fleet / ArgoCD / alert health — before you open an episode.*

---

## Why this demo exists

Most “AI for Kubernetes” demos stop at a chat answer: *“Looks like OOMKilled — bump the memory limit.”* Useful, but incomplete.

In production, the interesting loop is longer:

1. Something breaks in the cluster (alert fires).
2. You need **evidence**, not vibes — Prometheus, ArgoCD, pod state, chart history.
3. You need a **structured root cause** you can trust (and show a customer).
4. You need a **fix that lands as a PR** — GitOps-friendly, reviewable, mergeable.
5. You want that loop to be **repeatable** across environments, not a one-off prompt.

That’s what **cursor-k8s-ballast** is for: a small GitOps lab where Cursor isn’t a sidekick for autocomplete — it’s the investigator and the remediator.

<!-- MEDIUM: Architecture diagram — kind + ArgoCD + Prometheus + Ballast API/console + Cursor Cloud Agent -->
![Architecture: Ballast + Cursor in the loop](SCREENSHOT_PLACEHOLDER_architecture_diagram.png)
*Caption: Division of labour — cluster and observability stay read-only; Cursor investigates and opens the fix PR.*

---

## The incident (in one paragraph)

Five interdependent services ship via **Helm + ArgoCD**. We open a “bad chart bump” PR that lowers `ingest` memory limit below its startup working set. After merge, ArgoCD syncs, the kubelet **OOM-kills** the container, pods enter **CrashLoopBackOff**, and Prometheus fires **`StreamIngestCrashLooping`**.

The question isn’t “what’s wrong?” — it’s whether an agent can **correlate rollout ↔ alert**, respect **blast radius**, recommend **forward-fix vs rollback**, and then **file an issue + open a fix PR** without mutating the cluster by hand.

<!-- MEDIUM: Side-by-side — healthy ingest pods vs CrashLoopBackOff after break -->
![Before/after: ingest pods](SCREENSHOT_PLACEHOLDER_pods_before_after.png)
*Caption: Left: healthy. Right: CrashLoopBackOff after the bad memory limit lands on `main`.*

---

## Cursor features we actually used

This post is about **Cursor the product**, exercised end-to-end in that lab. Here’s the feature map.

| Cursor capability | Where it shows up in the demo |
|---|---|
| **Cloud Agents** | Live RCA investigation against the repo + brief; remediation agent that opens the forward-fix PR |
| **`@cursor/sdk`** | `sdk-runner/` launches and streams cloud agent runs from the Ballast API |
| **MCP (Model Context Protocol)** | Read-only `ballast` + `mcp-grafana` tools for alerts, PromQL, rollout, blast radius |
| **Evidence screenshots** | Playwright captures of Prometheus / ArgoCD / Grafana attached to the RCA |
| **Auto-remediation** | After RCA: GitHub issue → Cursor agent → forward-fix PR (e.g. [#24](https://github.com/pete-leese/cursor-k8s-ballast/issues/24) → [#25](https://github.com/pete-leese/cursor-k8s-ballast/pull/25)), surfaced back in the UI |
| **Bugbot (`@cursor review`)** | PR review on the remediation fix — e.g. clean Bugbot pass on [#25](https://github.com/pete-leese/cursor-k8s-ballast/pull/25) |
| **IDE + console loop** | Engineers discuss findings in Ballast; Cursor continues the conversation grounded in the RCA |

---

## 1. Cloud Agents: investigation that runs where the repo lives

The deterministic engine (`ballast/engine.py`) proves the **contract** — brief in, validated RCA out. The product story is the **Cursor Cloud Agent** path:

- Ballast assembles an investigation brief (alert, rollout, ArgoCD, topology).
- A Cloud Agent is launched via **`@cursor/sdk`** (`sdk-runner/`).
- The agent works against the **target repo** (chart values, GitOps layout, runbook context).
- Output is validated against a strict **RCA schema** — fail closed if the shape is wrong.

That “brief-in / contract-out” pattern is the same idea as other Cursor RCA demos, reused here for **Kubernetes/GitOps** instead of an app code path — which is the FDE point: **patterns travel; environments change.**

<!-- MEDIUM: Cursor Cloud Agent run page (cursor.com/agents/…) mid-investigation -->
![Cursor Cloud Agent investigating the incident](SCREENSHOT_PLACEHOLDER_cloud_agent_investigation.png)
*Caption: A live Cloud Agent run — tools, reasoning, and progress toward a contract-shaped RCA.*

<!-- MEDIUM: Ballast Investigation tab — agent activity feed -->
![Ballast Investigation tab — live agent activity](SCREENSHOT_PLACEHOLDER_console_investigation_feed.png)
*Caption: The Ballast console mirrors agent activity while the Cloud Agent works.*

### Why Cloud Agents matter here

Local chat can’t always reach your Mac’s Prometheus/Grafana. Cloud Agents clone the repo and run with the instructions and MCP surface you give them. For the demo we also support **`CURSOR_RUNTIME=local`** when you need localhost MCP — the product flexibility is the point.

---

## 2. MCP: give the agent eyes, not root

Two MCP servers ship with the lab:

- **`ballast`** — read-only triage: firing alerts, PromQL, rollout status, blast radius, run RCA.
- **`mcp-grafana`** — official Grafana MCP (Viewer token) for dashboards and metrics exploration.

The agent **investigates**; it does not `kubectl apply` a hotfix. Cluster mutation stays in **Git** (`break.sh` / `fix.sh` / remediation PRs). That boundary is deliberate: Cursor is powerful *because* the blast radius of the agent is constrained.

<!-- MEDIUM: .mcp.json or Cursor MCP settings showing ballast + grafana servers -->
![Cursor MCP configuration](SCREENSHOT_PLACEHOLDER_mcp_servers.png)
*Caption: Read-only MCP servers wired into Cursor — observability without write access to the cluster.*

<!-- MEDIUM: Grafana UI or MCP tool result during investigation -->
![Grafana / MCP evidence](SCREENSHOT_PLACEHOLDER_grafana_mcp.png)
*Caption: Metrics context the agent can pull via mcp-grafana while building the RCA.*

---

## 3. Screenshots as first-class evidence

A text RCA that says “Prometheus shows CrashLooping” is weaker than an RCA that **shows the alerts page and the ArgoCD app** at investigation time.

During triage, Ballast captures PNGs (Playwright) and stores them as investigation artifacts:

- **Prometheus** — firing alerts UI (or a snapshot fallback)
- **ArgoCD** — application sync/health (live UI or API-rendered snapshot)
- **Grafana** — dashboard capture when port-forward + auth are available

Those images land under **Root cause → Evidence** in the console, next to deeplinks an engineer can open in one click.

<!-- MEDIUM: Root Cause → Evidence expander with three screenshot columns -->
![Evidence screenshots in Ballast](SCREENSHOT_PLACEHOLDER_evidence_screenshots.png)
*Caption: Prometheus, ArgoCD, and Grafana captures attached to the investigation — evidence you can show in a war room.*

*Setup note for readers reproducing the lab:* `task setup:playwright`, then port-forward Prometheus / Grafana / ArgoCD (`task cluster:forward`).

---

## 4. Auto-remediation: from RCA to GitHub issue to fix PR

When the RCA recommends **forward-fix** (or rollback) and auto-remediation is enabled (`BALLAST_AUTO_REMEDIATE=1` + `CURSOR_API_KEY`):

1. Ballast files a **GitHub issue** from the RCA (structured body via `format-rca-issue.sh`).
2. A **Cursor Cloud Agent** is launched with `autoCreatePR: true` (`sdk-runner/remediate.mjs`).
3. The agent restores the healthy memory limit in Git and **opens a PR** — it does **not** merge it.
4. The Ballast UI surfaces **issue URL + PR URL** under Recommended action, and the **timeline** records issue filed → PR opened → PR merged (once a human merges).

That’s the product story: Cursor doesn’t just narrate the outage — it **produces the change request** your GitOps pipeline already knows how to sync.

### A real example from this lab

In one run of the demo, remediation produced:

- **Issue:** [#24](https://github.com/pete-leese/cursor-k8s-ballast/issues/24) — RCA-backed incident write-up  
- **Fix PR:** [#25](https://github.com/pete-leese/cursor-k8s-ballast/pull/25) — `fix(ingest): restore memory limit to 128Mi (Ballast RCA)`

PR #25 is a one-line GitOps fix (`16Mi` → `128Mi` in `deploy/services/ingest.values.yaml`), authored by the **Cursor Agent**, with a body that links the issue and explains *why forward-fix beats rollback* (single-field regression; avoid disrupting `transcode` / `catalog` / `recommendations` / `playback`).

The PR also ships with Cursor’s **Open in Web / Open in Cursor** affordances — the same agent run is one click away from the IDE.

<!-- MEDIUM: Recommended action panel with GitHub issue + Forward-fix PR buttons -->
![Auto-remediation links in the console](SCREENSHOT_PLACEHOLDER_autofix_issue_pr.png)
*Caption: Issue filed and fix PR opened — returned to the UI as part of the same investigation.*

<!-- MEDIUM: GitHub PR #25 opened by the remediation agent (title + summary table) -->
![Forward-fix PR #25 on GitHub](SCREENSHOT_PLACEHOLDER_github_fix_pr.png)
*Caption: [PR #25](https://github.com/pete-leese/cursor-k8s-ballast/pull/25) — Cursor Agent restores `resources.limits.memory` to 128Mi; Fixes #24.*

<!-- MEDIUM: Timeline with remediation events (issue / PR / merge) at the top -->
![Timeline including remediation](SCREENSHOT_PLACEHOLDER_timeline_remediation.png)
*Caption: Chronological incident timeline — latest first — including auto-remediation milestones.*

---

## 5. Bugbot (`@cursor review`): keep the agent honest on the PR

Cloud Agents are fast. Review still matters — and in this lab it’s a first-class Cursor product moment.

On [PR #25](https://github.com/pete-leese/cursor-k8s-ballast/pull/25), after the remediation agent pushed the fix, a human triggered:

```text
@cursor review
```

**Cursor Bugbot** responded on the same PR:

> ✅ Bugbot reviewed your changes and found no new issues!

That’s the intended loop: **agent authors the GitOps diff → Bugbot reviews the PR → human merges**. Agents propose; review gates still apply. You can re-trigger with `@cursor review` or `bugbot run` anytime.

Why this matters for Kubernetes/GitOps specifically: a “simple” values tweak can still be wrong. Earlier in the lab we saw that lowering **limits** without aligning **requests** makes Kubernetes reject the Deployment — ArgoCD sync fails with a validation error. Bugbot is the automated check that sits *before* that failure mode reaches the cluster.

<!-- MEDIUM: PR #25 showing @cursor review comment + Bugbot “no new issues” reply -->
![Bugbot on remediation PR #25](SCREENSHOT_PLACEHOLDER_bugbot_pr_review.png)
*Caption: [PR #25](https://github.com/pete-leese/cursor-k8s-ballast/pull/25) — `@cursor review` → Bugbot clean on the forward-fix commit.*

---

## 6. Discuss findings: chat grounded in the RCA

After the RCA completes, the Root Cause screen isn’t a dead PDF. **Discuss findings** lets you ask follow-ups — blast radius, why forward-fix beats rollback, which evidence is strongest — via the **Cursor Cloud Agents API**, grounded in the stored RCA + live cluster context.

That’s Cursor as a **war-room copilot**, not a one-shot summary generator.

<!-- MEDIUM: Discuss findings chat with starter prompts -->
![Discuss findings on Root Cause](SCREENSHOT_PLACEHOLDER_discuss_findings.png)
*Caption: Follow-up Q&A on the completed RCA — same investigation, continued with Cursor.*

---

## The human-in-the-loop GitOps path

We deliberately keep merges manual by default (`BALLAST_AUTO_MERGE=0`):

1. **`task break`** — opens an incident PR (bad memory bump).
2. Human merges → ArgoCD syncs → alert fires.
3. Ballast / Cloud Agent investigates → RCA + screenshots.
4. Auto-remediation opens the **fix PR**.
5. Human (+ Bugbot) reviews → merge → ArgoCD restores health.

Cursor accelerates investigation and authoring. **Git remains the control plane.**

<!-- MEDIUM: ArgoCD application Healthy/Synced after fix merge -->
![ArgoCD healthy after fix](SCREENSHOT_PLACEHOLDER_argocd_healthy.png)
*Caption: After the fix PR merges, ArgoCD converges — the same path you’d use in production GitOps.*

---

## What “good” looks like in the console

When nothing’s wrong, Ballast shouldn’t invent an incident. The default view is
**Fleet board**: pipeline health, ArgoCD sync, **stream-related** firing alerts
(not kind control-plane noise). **Triage fleet** only deep-dives when
`StreamIngestCrashLooping` is actually firing — otherwise: *fleet looks good.*

When something *is* wrong, one investigation should cover the episode — not a new run every 15 seconds while the alert stays open.

<!-- MEDIUM: Fleet board — everything looks good -->
![Healthy fleet board](SCREENSHOT_PLACEHOLDER_overview_healthy.png)
*Caption: Green path — no Ballast alerts, workloads healthy.*

<!-- MEDIUM: Fleet board — StreamIngestCrashLooping firing -->
![Incident fleet board](SCREENSHOT_PLACEHOLDER_overview_incident.png)
*Caption: Incident path — investigate once, dig into timeline / evidence / root cause / fix PR.*

---

## Try it yourself (short path)

```bash
task setup
task setup:playwright          # evidence screenshots
task cluster:up                # kind + monitoring + ArgoCD + apps
task cluster:forward           # Prometheus / Grafana / ArgoCD locally
task demo                      # Ballast API + UI (live Cursor Cloud Agent)

task break                     # open incident PR → merge to main
# wait for CrashLoop + alert
# click Triage fleet (or let alert watch start one run)

# with CURSOR_API_KEY + BALLAST_AUTO_REMEDIATE=1:
# issue + fix PR appear under Recommended action
```

Full narrative: `docs/incident-runbook.md` in the repo.

---

## Takeaways for teams evaluating Cursor

1. **Cloud Agents** turn a repo + brief into a durable investigation artifact — not a disposable chat.
2. **MCP** is how you give agents production eyes without giving them production hands.
3. **Screenshots and contracts** make AI output reviewable in an incident channel.
4. **Auto-remediation via PR** fits GitOps; merge policy stays yours.
5. **Bugbot** closes the loop on agent-authored diffs.
6. **Discuss** keeps the RCA alive as a working document.

Cursor isn’t replacing your Prometheus or ArgoCD. It’s the layer that **connects signal → explanation → change request** — with humans still owning the merge.

---

## Appendix: screenshot checklist (for editors)

Use this list when assembling the Medium draft in the UI (Medium prefers uploaded images over raw markdown image links):

| Placeholder file | Suggested shot |
|---|---|
| `SCREENSHOT_PLACEHOLDER_cover_cluster_overview.png` | Ballast UI, fleet board |
| `SCREENSHOT_PLACEHOLDER_architecture_diagram.png` | Architecture / sequence diagram |
| `SCREENSHOT_PLACEHOLDER_pods_before_after.png` | `kubectl get pods` before/after break |
| `SCREENSHOT_PLACEHOLDER_cloud_agent_investigation.png` | cursor.com agent run |
| `SCREENSHOT_PLACEHOLDER_console_investigation_feed.png` | Ballast Investigation tab |
| `SCREENSHOT_PLACEHOLDER_mcp_servers.png` | MCP config in Cursor |
| `SCREENSHOT_PLACEHOLDER_grafana_mcp.png` | Grafana or MCP tool output |
| `SCREENSHOT_PLACEHOLDER_evidence_screenshots.png` | Evidence expander with PNGs |
| `SCREENSHOT_PLACEHOLDER_autofix_issue_pr.png` | Issue + PR buttons in UI |
| `SCREENSHOT_PLACEHOLDER_github_fix_pr.png` | [PR #25](https://github.com/pete-leese/cursor-k8s-ballast/pull/25) title + summary |
| `SCREENSHOT_PLACEHOLDER_timeline_remediation.png` | Timeline with remediation events |
| `SCREENSHOT_PLACEHOLDER_bugbot_pr_review.png` | PR #25: `@cursor review` + Bugbot “no new issues” |
| `SCREENSHOT_PLACEHOLDER_discuss_findings.png` | Discuss findings chat |
| `SCREENSHOT_PLACEHOLDER_argocd_healthy.png` | ArgoCD app healthy post-fix |
| `SCREENSHOT_PLACEHOLDER_overview_healthy.png` | Green overview |
| `SCREENSHOT_PLACEHOLDER_overview_incident.png` | Firing-alert overview |

---

*Written for a Cursor-focused audience. Demo lab: cursor-k8s-ballast. Replace placeholders with your own captures before publishing on Medium.*
