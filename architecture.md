# k8s-ballast — architecture

This document describes the shape of the system and the **seams** that keep the
prototype honest about what would change in production. It is the Kubernetes /
GitOps sibling of `cursor-causa`'s architecture: the same division of labour,
applied to a different incident class (a bad Helm chart bump instead of an app
code regression).

## Division of labour

k8s-ballast is split along one deliberate line: **cheap deterministic triage**
vs **expensive semantic investigation**.

- **ballast (triage).** Given a CrashLoopBackOff alert, narrow the search space
  with data that is cheap to fetch and needs no reasoning: the alert fire time
  from Prometheus, the rollout timestamp from Kubernetes (the current
  ReplicaSet's creation time), the offending resource limit from the live
  Deployment, and the blast radius from the declared `topology.yaml`. Assemble a
  structured **investigation brief**. This is scripted and reproducible
  (`ballast/engine.py::assemble_brief`).
- **Investigator (analysis).** Turn the brief into a strict RCA. Three
  implementations behind one contract:
  - the deterministic **engine** (`analyze`) — correlates rollout↔alert,
    characterises the resource change, computes blast radius, recommends
    rollback vs forward-fix. No LLM; the demo's reliability rests here.
  - the **mock** — replays a fixture RCA (`fixtures/rca_payments.json`).
  - the **Cursor Cloud Agent** — reads the same brief and the read-only
    Prometheus/Grafana MCP tools, traces the chart/git history semantically, and
    returns JSON validated against the same contract.

The brief flows in, the RCA contract flows out. That `brief-in / contract-out`
discipline is what makes the demo repeatable rather than a one-off prompt.

## Components

```
kube-state-metrics ─> Prometheus rule (BallastServiceCrashLooping) ─> Alertmanager
                                                     │
        ballast triage ─ PrometheusSource (HTTP, read-only) ────────┤
                       ─ KubernetesSource (kubectl: rollout ts, crash state, limits)
                       ─ DeclaredTopologySource (topology.yaml) ── blast radius
                                                     │
                       investigation brief ──────────┤
                                                     ▼
                       Investigator
                         ├── engine   (deterministic analyze -> RCA)
                         ├── mock     (fixture -> RCA)
                         └── cursor   (Cloud Agent via sdk-runner)
                                                     │
                       RCA (validated against ballast/contract.py)
```

## Seams (where production differs from the prototype)

1. **`TopologySource`.** One method, `dependents(service) -> list[str]`.
   - *Prototype:* reads `topology.yaml`, a declared dependency graph.
   - *Production:* a service-mesh / Consul MCP implementation derives the live
     graph. The blast-radius reasoning in the RCA does not change; only the data
     source. **Declared graph for the prototype, mesh/Consul in production.**

2. **Rollout timestamp source.**
   - *Prototype:* the current ReplicaSet's `creationTimestamp` via `kubectl`.
   - *Production:* ArgoCD Application sync history (the `deploy/argocd/`
     Applications are the GitOps representation). The correlation logic is
     identical — only where the timestamp comes from changes.

3. **`Investigator`.** `engine` / `mock` / `cursor` behind the RCA contract. The
   contract is the trust boundary: a Cloud Agent's JSON is validated against
   `ballast/contract.py`; invalid output is rejected, never rendered as a real
   finding.

4. **Metrics access.**
   - *Prototype:* Prometheus HTTP API on a port-forward.
   - *Production:* a read-only Grafana/Prometheus MCP server with a Viewer
     service-account token (see `.mcp.json`).

## Guardrails

- **Read-only everywhere.** The Prometheus/Grafana MCP is read-only; the
  Kubernetes source only reads (`kubectl get`); the RCA engine never mutates the
  cluster. `break.sh` / `fix.sh` are explicit, human-run Helm operations.
- **Degrade, never crash.** If a triage source is unavailable, the brief records
  the gap in `degraded` and analysis proceeds with what it has.
- **The contract is the trust boundary.** Every RCA — engine, mock, or agent —
  is validated against `ballast/contract.py` before it is emitted.

## Deferred scope (noted, not built)

- Live `TopologySource` from a service mesh / Consul MCP.
- ArgoCD-driven GitOps for the bad bump (a commit that lowers the limit) with
  ArgoCD sync history as the rollout timestamp source.
- ballast emitting its own OTel traces for triage/analysis latency.
