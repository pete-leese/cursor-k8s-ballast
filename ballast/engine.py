"""The deterministic RCA engine.

Given a service, this runs cheap triage against the live cluster (Prometheus +
Kubernetes) and the declared topology, correlates the rollout timestamp with Kubernetes,
ArgoCD, and (when present) Prometheus alert signals, characterises the offending resource change, and emits a
strict RCA validated against ``ballast.contract.RCA``.

This is the ``engine`` investigator: it needs no LLM and no Cursor call, so the
demo is reliable. A Cursor Cloud Agent (``CursorInvestigator``) can produce the
same contract from the same brief, tracing the chart/git history semantically —
that is the "pattern reuse" the FDE story is about.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .argocd_evidence import argocd_evidence_items
from .brief import AlertContext, ArgoCDContext, InvestigationBrief, RepoTarget, RolloutContext
from .contract import (
    RCA,
    Action,
    BlastRadius,
    Confidence,
    Evidence,
    EvidenceSource,
    GeneratedBy,
    RecommendedAction,
    ResourceChange,
    RolloutCorrelation,
    TelemetrySignal,
    TimelineEvent,
    TimelineKind,
)
from .prometheus_evidence import prometheus_alerts_url
from .screenshot import grafana_dashboard_url
from .sources import ArgoCDSource, KubernetesSource, PrometheusSource, _parse_ts
from .topology import DeclaredTopologySource

_ROOT = Path(__file__).resolve().parent.parent

# Default deep links for a local kind + kube-prometheus-stack setup.
PROM_ALERTS_URL = prometheus_alerts_url()
PROM_GRAPH_URL = "http://localhost:9090/graph"
GRAFANA_URL = "http://localhost:3000"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def assemble_brief(
    *,
    investigation_id: str,
    service: str,
    namespace: str,
    prometheus: PrometheusSource | None,
    kubernetes: KubernetesSource | None,
    topology: DeclaredTopologySource,
    healthy_memory: str | None,
    repo_url: str,
    repo_ref: str = "main",
    alertname: str = "StreamIngestCrashLooping",
    argocd: ArgoCDSource | None = None,
) -> InvestigationBrief:
    """Run triage and assemble the brief, degrading (never crashing) per source."""
    degraded: list[str] = []
    fired_at: str | None = None
    expr = severity = None
    labels: dict[str, str] = {}

    if prometheus is not None:
        try:
            alert = prometheus.firing_alert(alertname) or prometheus.firing_alert()
            if alert:
                fired_at = alert.get("activeAt")
                labels = alert.get("labels", {})
                severity = labels.get("severity")
                expr = alert.get("annotations", {}).get("description")
        except Exception as exc:  # degrade, never crash
            degraded.append(f"prometheus unavailable: {exc}")
    else:
        degraded.append("prometheus source not configured")

    rollout_at = current_mem = None
    crash: dict = {}
    if kubernetes is not None:
        try:
            dt = kubernetes.rollout_time(service)
            rollout_at = _iso(dt) if dt else None
            current_mem = kubernetes.memory_limit(service)
            crash = kubernetes.crash_state(service)
        except Exception as exc:
            degraded.append(f"kubernetes unavailable: {exc}")
    else:
        degraded.append("kubernetes source not configured")

    argocd_ctx: ArgoCDContext | None = None
    if argocd is not None:
        try:
            raw = argocd.application_context(service)
            if raw:
                argocd_ctx = ArgoCDContext.model_validate(raw)
        except Exception as exc:
            degraded.append(f"argocd unavailable: {exc}")
    else:
        degraded.append("argocd source not configured")

    alert_observed = fired_at is not None
    if not fired_at:
        # Symptom anchor when investigating from kube/Argo before the alert fires.
        if argocd_ctx and argocd_ctx.last_sync_finished:
            fired_at = argocd_ctx.last_sync_finished
        elif rollout_at:
            fired_at = rollout_at
        else:
            fired_at = _now_iso()

    return InvestigationBrief(
        investigation_id=investigation_id,
        service=service,
        namespace=namespace,
        alert=AlertContext(
            alertname=alertname,
            fired_at=fired_at,
            observed=alert_observed,
            expr=expr,
            severity=severity,
            labels=labels,
        ),
        rollout=RolloutContext(
            service=service,
            namespace=namespace,
            rollout_at=rollout_at,
            current_memory_limit=current_mem,
            healthy_memory_limit=healthy_memory,
            crash_state=crash,
        ),
        blast_radius_hint=topology.dependents(service),
        repo=RepoTarget(url=repo_url, ref=repo_ref, chart_path="charts/ballast-service"),
        argocd=argocd_ctx,
        degraded=degraded,
    )


def analyze(
    brief: InvestigationBrief,
    *,
    window_seconds: int = 600,
    chart_version_from: str | None = None,
    chart_version_to: str | None = None,
) -> RCA:
    """Turn a brief into a validated RCA using multi-signal deterministic rules.

    Correlates Kubernetes crash state, ArgoCD sync/health, and (when observed)
    the Prometheus alert against the rollout timestamp — not alert-only.
    """
    service = brief.service
    ns = brief.namespace
    dependents = brief.blast_radius_hint
    crash = brief.rollout.crash_state or {}
    alert_observed = brief.alert.observed

    # --- crash / resource signals -------------------------------------------
    oom = (
        crash.get("last_terminated_reason") == "OOMKilled"
        or crash.get("exit_code") == 137
    )
    waiting = crash.get("waiting_reason")
    restarts = crash.get("restarts", 0)
    crash_signal = bool(oom or waiting == "CrashLoopBackOff")

    current_mem = brief.rollout.current_memory_limit or "unknown"
    healthy_mem = brief.rollout.healthy_memory_limit or "unknown"
    mem_regressed = (
        current_mem != "unknown"
        and healthy_mem != "unknown"
        and current_mem != healthy_mem
    )

    argo = brief.argocd
    argo_bad = False
    if argo is not None:
        argo_bad = argo.health_status in ("Degraded", "Missing", "Suspended") or (
            argo.sync_status == "OutOfSync"
        ) or (argo.health_status == "Progressing" and crash_signal)

    # --- rollout <-> symptom correlation ------------------------------------
    symptom_iso = brief.alert.fired_at
    if not alert_observed and argo and argo.last_sync_finished:
        symptom_iso = argo.last_sync_finished
    rollout_iso = brief.rollout.rollout_at or symptom_iso
    alert_dt = _parse_ts(symptom_iso)
    rollout_dt = _parse_ts(rollout_iso)
    delta = (alert_dt - rollout_dt).total_seconds()
    correlated = 0 <= delta <= window_seconds
    correlation = RolloutCorrelation(
        rollout_at=_iso(rollout_dt),
        alert_fired_at=_iso(alert_dt),
        delta_seconds=round(delta, 1),
        correlated=correlated,
        window_seconds=window_seconds,
    )

    # --- the resource regression --------------------------------------------
    resource_change = ResourceChange(
        field="resources.limits.memory",
        previous=healthy_mem,
        current=current_mem,
        chart_version_from=chart_version_from,
        chart_version_to=chart_version_to,
        note=(
            f"The chart bump lowered {service}'s memory limit to {current_mem}, "
            f"below the container's ~40Mi startup ballast working set. The kubelet "
            f"OOM-kills the container before it becomes ready, so it enters "
            f"CrashLoopBackOff. Restoring the limit to {healthy_mem} is a "
            f"one-field forward-fix."
        ),
    )

    # --- timeline (all available signals) -----------------------------------
    timeline = [
        TimelineEvent(
            timestamp=correlation.rollout_at,
            kind=TimelineKind.rollout,
            label=(
                f"Rollout of {service} shipped resources.limits.memory="
                f"{current_mem} (chart {chart_version_to or 'bumped'})"
            ),
        ),
        TimelineEvent(
            timestamp=correlation.rollout_at,
            kind=TimelineKind.chart_bump,
            label=f"charts/ballast-service values: memory {healthy_mem} -> {current_mem}",
        ),
    ]
    if argo is not None:
        argo_ts = (
            argo.last_sync_finished
            or argo.last_sync_started
            or correlation.rollout_at
        )
        timeline.append(
            TimelineEvent(
                timestamp=argo_ts,
                kind=TimelineKind.argocd,
                label=(
                    f"ArgoCD `{argo.application or service}`: "
                    f"sync={argo.sync_status or '?'}, "
                    f"health={argo.health_status or '?'}"
                    + (
                        f", revision={(argo.revision or '')[:12]}"
                        if argo.revision
                        else ""
                    )
                ),
            )
        )
    if crash_signal:
        timeline.append(
            TimelineEvent(
                timestamp=correlation.alert_fired_at,
                kind=TimelineKind.crashloop,
                label=(
                    f"{service} pods "
                    + (
                        "OOMKilled and entered CrashLoopBackOff"
                        if oom
                        else "entered CrashLoopBackOff"
                    )
                    + f" ({restarts} restarts observed)"
                ),
            )
        )
    if alert_observed:
        timeline.append(
            TimelineEvent(
                timestamp=correlation.alert_fired_at,
                kind=TimelineKind.alert,
                label=f"{brief.alert.alertname} fired for {service}",
                deeplink=PROM_ALERTS_URL,
            )
        )
    else:
        timeline.append(
            TimelineEvent(
                timestamp=correlation.alert_fired_at,
                kind=TimelineKind.note,
                label=(
                    f"{brief.alert.alertname} not observed yet — investigating from "
                    f"Kubernetes"
                    + (" + ArgoCD" if argo is not None else "")
                    + " signals"
                ),
            )
        )

    # --- evidence -----------------------------------------------------------
    evidence = [
        Evidence(
            source=EvidenceSource.chart,
            detail=(
                f"charts/ballast-service values for {service} set "
                f"resources.limits.memory={current_mem}; the previous healthy "
                f"value was {healthy_mem}. This is the only field that changed."
            ),
            deeplink=None,
        ),
        Evidence(
            source=EvidenceSource.kubernetes,
            detail=(
                f"Pod container state: waiting.reason={waiting}, "
                f"lastState.terminated.reason={crash.get('last_terminated_reason')}, "
                f"exitCode={crash.get('exit_code')}, restarts={restarts}. "
                f"OOMKilled + exitCode 137 is a memory-limit kill, not a code crash."
            ),
            deeplink=None,
        ),
    ]
    if alert_observed:
        evidence.append(
            Evidence(
                source=EvidenceSource.prometheus,
                detail=(
                    f"{brief.alert.alertname} is firing; alert activeAt "
                    f"{correlation.alert_fired_at} is {correlation.delta_seconds:.0f}s "
                    f"after the rollout at {correlation.rollout_at} "
                    f"({'within' if correlated else 'outside'} the "
                    f"{window_seconds}s correlation window)."
                ),
                deeplink=PROM_ALERTS_URL,
            )
        )
    else:
        evidence.append(
            Evidence(
                source=EvidenceSource.prometheus,
                detail=(
                    f"{brief.alert.alertname} is not firing yet (for: window or "
                    f"scrape lag). Rollout at {correlation.rollout_at} still "
                    f"correlates with live Kubernetes crash evidence"
                    f"{' and ArgoCD health' if argo_bad else ''} "
                    f"({correlation.delta_seconds:.0f}s symptom delta, "
                    f"{'within' if correlated else 'outside'} {window_seconds}s window)."
                ),
                deeplink=PROM_ALERTS_URL,
            )
        )
    if brief.argocd is not None:
        evidence.extend(argocd_evidence_items(brief.argocd, service))

    # --- supporting telemetry (verifiable PromQL) ---------------------------
    telemetry = [
        TelemetrySignal(
            signal="CrashLoopBackOff waiting reason",
            query=(
                'kube_pod_container_status_waiting_reason'
                f'{{namespace="{ns}", reason="CrashLoopBackOff", '
                f'container="{service}"}}'
            ),
            observation=(
                f"Value 1 for {service} — the kubelet is holding the container in "
                f"CrashLoopBackOff."
                if waiting == "CrashLoopBackOff"
                else f"Waiting reason={waiting!r}; confirm via PromQL / kubectl."
            ),
            deeplink=PROM_GRAPH_URL,
        ),
        TelemetrySignal(
            signal="container restarts",
            query=(
                'max(kube_pod_container_status_restarts_total'
                f'{{namespace="{ns}", container="{service}"}})'
            ),
            observation=f"Restart count climbing ({restarts} observed) with backoff.",
            deeplink=PROM_GRAPH_URL,
        ),
        TelemetrySignal(
            signal="Ballast RCA Grafana dashboard",
            query=None,
            observation=(
                f"kube-state-metrics view for {service}: CrashLoop, OOMKilled, "
                f"memory working set vs limit, restarts."
            ),
            deeplink=grafana_dashboard_url(service),
        ),
    ]

    # --- blast radius -------------------------------------------------------
    blast = BlastRadius(
        if_rolled_back=dependents,
        graph_source="declared:topology.yaml",
        note=(
            f"{len(dependents)} service(s) depend on {service} "
            f"({', '.join(dependents) or 'none'}). A full chart rollback churns "
            f"{service} again and briefly disrupts all of them; a targeted "
            f"memory-limit forward-fix touches only {service}."
        )
        if dependents
        else f"No services depend on {service}; a rollback has no downstream blast radius.",
    )

    # --- multi-signal confidence --------------------------------------------
    agreeing: list[str] = []
    if crash_signal:
        agreeing.append("Kubernetes CrashLoop/OOM")
    if mem_regressed:
        agreeing.append(f"memory limit {current_mem}≠{healthy_mem}")
    if alert_observed:
        agreeing.append("Prometheus alert")
    if argo_bad and argo is not None:
        agreeing.append(f"ArgoCD {argo.health_status or argo.sync_status}")
    signal_count = len(agreeing)

    # --- recommendation -----------------------------------------------------
    if crash_signal or (mem_regressed and argo_bad):
        if dependents:
            action = Action.forward_fix
            reasoning = (
                f"The regression is a single field (memory limit {healthy_mem} -> "
                f"{current_mem}) and the fix is trivial and low-risk. A full "
                f"rollback of the chart bump would also revert any unrelated "
                f"changes in it and re-roll {service}, disrupting {len(dependents)} "
                f"downstream service(s): {', '.join(dependents)}. Prefer a targeted "
                f"forward-fix that restores the limit only."
            )
        else:
            action = Action.rollback
            reasoning = (
                f"Nothing depends on {service}, so a rollback is clean and fastest. "
                f"Forward-fix (restore the memory limit) is equally valid."
            )
        remediation = (
            f"helm upgrade {service} charts/ballast-service -n {ns} "
            f"--reuse-values --set resources.limits.memory={healthy_mem}   "
            f"# or set it back in deploy/services/{service}.values.yaml and let ArgoCD sync"
        )
        if signal_count >= 3 and correlated:
            confidence_score = 0.95
        elif signal_count >= 2 and (correlated or crash_signal):
            confidence_score = 0.9 if (crash_signal and mem_regressed) else 0.8
        else:
            confidence_score = 0.7
        confidence_rationale = (
            f"{signal_count} independent signal(s) agree: {', '.join(agreeing) or 'none'}. "
            f"Symptom time is {correlation.delta_seconds:.0f}s after rollout "
            f"({'inside' if correlated else 'outside'} the {window_seconds}s window)"
            + (
                "; Prometheus alert observed."
                if alert_observed
                else "; Prometheus alert not yet observed — kube/Argo drove triage."
            )
        )
    else:
        action = Action.investigate_more
        reasoning = (
            "No OOMKilled / CrashLoopBackOff signal was observed in the cluster; "
            "the resource-limit hypothesis is not confirmed."
        )
        remediation = f"kubectl -n {ns} describe deploy {service}"
        confidence_score = 0.3
        confidence_rationale = (
            "Crash signals absent; multi-signal correlation inconclusive "
            f"(saw: {', '.join(agreeing) or 'none'})."
        )

    summary = (
        f"A chart bump lowered {service}'s memory limit to {current_mem} "
        f"(from {healthy_mem}), OOM-killing the container on startup and driving it "
        f"into CrashLoopBackOff ~{correlation.delta_seconds:.0f}s later."
    )
    if not alert_observed:
        summary += (
            f" Investigation started from Kubernetes"
            + (" and ArgoCD" if argo is not None else "")
            + f" before `{brief.alert.alertname}` fired."
        )

    return RCA(
        investigation_id=brief.investigation_id,
        service=service,
        namespace=ns,
        generated_by=GeneratedBy.engine,
        summary=summary,
        confidence=Confidence(score=confidence_score, rationale=confidence_rationale),
        timeline=timeline,
        rollout_correlation=correlation,
        resource_change=resource_change,
        evidence=evidence,
        supporting_telemetry=telemetry,
        blast_radius=blast,
        recommended_action=RecommendedAction(
            action=action, reasoning=reasoning, remediation=remediation
        ),
    )
