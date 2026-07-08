"""The investigation brief: the structured input ballast hands to an investigator.

This is the "brief-in" half of brief-in / contract-out. Triage (Prometheus +
Kubernetes + topology) produces this; an investigator (the deterministic engine,
a mock, or a Cursor Cloud Agent) consumes it. Keeping it a typed model means the
prompt the agent receives is reproducible rather than hand-written.
"""

from __future__ import annotations

from pydantic import BaseModel


class AlertContext(BaseModel):
    alertname: str
    fired_at: str  # ISO-8601
    expr: str | None = None
    severity: str | None = None
    labels: dict[str, str] = {}


class RolloutContext(BaseModel):
    service: str
    namespace: str
    rollout_at: str | None = None  # ISO-8601
    current_memory_limit: str | None = None
    healthy_memory_limit: str | None = None
    crash_state: dict = {}


class RepoTarget(BaseModel):
    url: str
    ref: str = "main"
    chart_path: str | None = None  # where the implicated chart/values live


class ArgoCDHistoryEntry(BaseModel):
    id: int | None = None
    deployed_at: str | None = None
    revision: str | None = None


class ArgoCDResourceResult(BaseModel):
    kind: str
    name: str
    namespace: str | None = None
    status: str | None = None
    message: str | None = None


class ArgoCDClusterEvent(BaseModel):
    timestamp: str
    type: str
    reason: str
    message: str


class ArgoCDContext(BaseModel):
    application: str
    sync_status: str | None = None
    health_status: str | None = None
    revision: str | None = None
    target_revision: str | None = None
    last_sync_started: str | None = None
    last_sync_finished: str | None = None
    last_sync_phase: str | None = None
    last_sync_message: str | None = None
    health_transition: str | None = None
    history: list[ArgoCDHistoryEntry] = []
    sync_resources: list[ArgoCDResourceResult] = []
    events: list[ArgoCDClusterEvent] = []


class InvestigationBrief(BaseModel):
    investigation_id: str
    service: str
    namespace: str
    alert: AlertContext
    rollout: RolloutContext
    blast_radius_hint: list[str]  # from topology; the agent confirms/uses it
    repo: RepoTarget
    argocd: ArgoCDContext | None = None
    degraded: list[str] = []  # triage sources that were unavailable

    def to_agent_prompt(self, rca_schema: str) -> str:
        """Render the brief into the prompt a Cursor Cloud Agent receives."""
        return (
            "You are a codebase/infrastructure investigator, not a code "
            f"generator. Investigate the following production incident in the "
            f"'{self.service}' Kubernetes service.\n\n"
            "INVESTIGATION BRIEF (JSON):\n"
            f"{self.model_dump_json(indent=2)}\n\n"
            "Tasks:\n"
            "1. Identify the Helm chart / values change that explains the "
            "CrashLoopBackOff (which field regressed, old vs new value).\n"
            "2. Confirm the rollout timestamp correlates with the alert firing "
            "time using the read-only Prometheus/Grafana MCP tools if available "
            "(query kube_pod_container_status_waiting_reason and "
            "kube_pod_container_status_last_terminated_reason for the namespace).\n"
            "3. Use blast_radius_hint to reason about whether a full rollback or "
            "a targeted forward-fix is safer, and give the exact remediation.\n\n"
            "Return ONLY a single JSON object that validates against this JSON "
            "Schema. No prose, no markdown fences, JSON only:\n\n"
            f"{rca_schema}"
        )
