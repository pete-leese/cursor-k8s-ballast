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
    fired_at: str  # ISO-8601 — Prometheus activeAt, or symptom anchor if not observed
    observed: bool = True  # False when kube/Argo triggered investigation before alert
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
        alert_note = (
            "Prometheus alert is observed and firing."
            if self.alert.observed
            else (
                "Prometheus alert is NOT observed yet (still in for: window or "
                "unreachable). Treat Kubernetes crash state and ArgoCD sync/health "
                "as primary signals — do not wait for the alert."
            )
        )
        return (
            "You are a codebase/infrastructure investigator, not a code "
            f"generator. Investigate the following production incident in the "
            f"'{self.service}' Kubernetes service.\n\n"
            "INVESTIGATION BRIEF (JSON):\n"
            f"{self.model_dump_json(indent=2)}\n\n"
            "Signal sources (correlate ALL that are present — do not rely on "
            "Prometheus alone):\n"
            f"- Prometheus: {alert_note}\n"
            "- Kubernetes API: pod waiting reason, last terminated reason / "
            "exit code, restarts, memory limit vs healthy.\n"
            "- ArgoCD: sync status, health, last sync revision/time, resource "
            "results, and recent Application events.\n"
            "- Chart / git: the values field that regressed.\n\n"
            "Tasks:\n"
            "1. Identify the Helm chart / values change that explains the "
            "CrashLoopBackOff (which field regressed, old vs new value).\n"
            "2. Build a timeline that correlates rollout time with Kubernetes "
            "crash evidence, ArgoCD sync/health transition, and (if observed) "
            "the Prometheus alert. Use read-only Prometheus/Grafana MCP tools "
            "when available (kube_pod_container_status_waiting_reason, "
            "kube_pod_container_status_last_terminated_reason).\n"
            "3. Weigh agreement across signals in confidence.rationale "
            "(e.g. OOM + bad memory limit + ArgoCD Degraded + alert).\n"
            "4. Use blast_radius_hint to reason about whether a full rollback or "
            "a targeted forward-fix is safer, and give the exact remediation.\n\n"
            "Return ONLY a single JSON object that validates against this JSON "
            "Schema. No prose, no markdown fences, JSON only:\n\n"
            f"{rca_schema}"
        )
