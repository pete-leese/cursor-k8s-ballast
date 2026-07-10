"""The RCA contract: the strict schema the investigator returns and ballast renders.

This module is the trust boundary of the whole system. A Cursor Cloud Agent is
prompted to return JSON matching ``RCA`` exactly; ballast validates that JSON
against this model before anything is stored or rendered. Invalid output is
rejected and surfaced as an error rather than displayed as if it were a real
finding.

Design note: this is "brief-in / contract-out". A loose "investigate this"
prompt produces unusable, unrepeatable output. By pinning the *shape* of the
answer here and generating a JSON Schema from it (``schema/rca.schema.json``),
we can hand the agent an exact target and fail closed when it deviates. Pydantic
v2 gives us both runtime validation and the JSON Schema export from one
definition.

This is the Kubernetes/GitOps RCA contract for the stream-fleet demo: the
incident is a bad Helm chart bump (resource limits set too low) that drives
``ingest`` into CrashLoopBackOff, and the evidence/telemetry come from
Prometheus, Kubernetes, and the chart/git history rather than an application
code path.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EvidenceSource(str, Enum):
    """Where a piece of evidence came from. Drives the icon/colour in a console."""

    prometheus = "prometheus"
    kubernetes = "kubernetes"
    argocd = "argocd"
    git = "git"
    chart = "chart"


class TimelineKind(str, Enum):
    """The type of a timeline event, so a console can style the incident timeline."""

    alert = "alert"
    rollout = "rollout"
    chart_bump = "chart_bump"
    crashloop = "crashloop"
    argocd = "argocd"
    note = "note"


class Action(str, Enum):
    """The recommended remediation. ``staged_rollout`` exists because a blunt
    rollback can have a wide blast radius (see ``BlastRadius``)."""

    rollback = "rollback"
    forward_fix = "forward_fix"
    staged_rollout = "staged_rollout"
    investigate_more = "investigate_more"


class GeneratedBy(str, Enum):
    """Which investigator produced this RCA. ``mock`` keeps the demo reliable
    without a live Cursor run; ``cursor`` is a real Cloud Agent investigation;
    ``engine`` is the deterministic on-cluster analyzer."""

    engine = "engine"
    mock = "mock"
    cursor = "cursor"


class Confidence(BaseModel):
    """A bounded confidence score plus a short human rationale. The score is
    constrained to 0..1 so a console can render it as a gauge without clamping."""

    score: float = Field(ge=0.0, le=1.0)
    rationale: str


class TimelineEvent(BaseModel):
    """One ordered event on the incident timeline (ballast's own synthesis)."""

    timestamp: str  # ISO-8601
    kind: TimelineKind
    label: str
    deeplink: str | None = None


class Evidence(BaseModel):
    """A single supporting fact, tagged by source and optionally deep-linked
    into Prometheus/Grafana/ArgoCD so an engineer can verify it in one click.

    ``screenshot_url`` is optional — populated when an investigator attaches a
    UI capture (ArgoCD / Prometheus / Grafana) that the console can render inline.
    """

    source: EvidenceSource
    detail: str
    deeplink: str | None = None
    screenshot_url: str | None = None


class RolloutCorrelation(BaseModel):
    """Rollout vs primary symptom time (alert, or kube/Argo anchor if no alert).

    ``delta_seconds`` is ``alert_fired_at - rollout_at``. A small positive delta
    fingerprints "this rollout caused the incident". ``alert_fired_at`` may be the
    Prometheus ``activeAt`` or a symptom anchor (ArgoCD sync / investigation time)
    when the alert is not yet observed. ``correlated`` is the engine's boolean
    call given the configured window."""

    rollout_at: str  # ISO-8601, when the offending ReplicaSet/rollout was created
    alert_fired_at: str  # ISO-8601 — alert or symptom-anchor time
    delta_seconds: float
    correlated: bool
    window_seconds: int


class ResourceChange(BaseModel):
    """The manifest-level diff the bad chart bump introduced. This is the
    Kubernetes analogue of a code diff: the field that regressed, old vs new."""

    field: str  # e.g. "resources.limits.memory"
    previous: str  # e.g. "128Mi"
    current: str  # e.g. "16Mi"
    chart_version_from: str | None = None
    chart_version_to: str | None = None
    note: str


class TelemetrySignal(BaseModel):
    """A metric signal that supports the conclusion, with the PromQL that
    produced it and a deeplink to the exact panel. ``deeplink`` is required here
    (unlike on ``Evidence``) because supporting telemetry must be verifiable."""

    signal: str  # e.g. "container OOMKilled restarts"
    query: str | None = None  # PromQL
    observation: str
    deeplink: str


class BlastRadius(BaseModel):
    """Downstream impact of rolling back. ``graph_source`` records provenance so
    the demo can show this came from the declared topology now, and would come
    from a service mesh / Consul MCP in production (the seam is deliberate)."""

    if_rolled_back: list[str]
    graph_source: str  # "declared:topology.yaml" | "consul-mcp" | ...
    note: str


class RecommendedAction(BaseModel):
    """The recommendation plus its reasoning, e.g. 'a full rollback also reverts
    unrelated chart changes and disrupts five dependents; restore the memory
    limit as a targeted forward-fix instead.'"""

    action: Action
    reasoning: str
    remediation: str  # the concrete command / manifest edit to apply


class RCA(BaseModel):
    """The root-cause-analysis contract. This is the product of an investigation."""

    schema_version: str = "1.0"
    investigation_id: str
    service: str
    namespace: str = "demo"
    generated_by: GeneratedBy
    summary: str  # one-line headline
    confidence: Confidence
    timeline: list[TimelineEvent]
    rollout_correlation: RolloutCorrelation
    resource_change: ResourceChange
    evidence: list[Evidence]
    supporting_telemetry: list[TelemetrySignal]
    blast_radius: BlastRadius
    recommended_action: RecommendedAction


if __name__ == "__main__":
    # Convenience: ``python -m ballast.contract`` prints the JSON Schema to stdout.
    import json

    print(json.dumps(RCA.model_json_schema(), indent=2))
