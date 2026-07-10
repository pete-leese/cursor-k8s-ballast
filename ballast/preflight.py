"""Pre-investigation and cluster health checks.

Incident readiness is multi-signal: Prometheus alerts, live Kubernetes pod
state, and ArgoCD sync/health are all considered. A CrashLoop / OOM from the
API is enough to investigate even before the Prometheus ``for:`` window elapses.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

from .sources import ArgoCDSource, KubernetesSource, PrometheusSource
from .store import STORE

BALLAST_SERVICES = ["ingest", "transcode", "playback", "recommendations", "catalog"]
DEFAULT_ALERT = os.environ.get("BALLAST_ALERTNAME", "StreamIngestCrashLooping")
# Demo fleet lives in `demo`; Ballast product stays in `ballast`.
DEFAULT_NAMESPACE = os.environ.get(
    "BALLAST_DEMO_NAMESPACE",
    os.environ.get("BALLAST_NAMESPACE", "demo"),
)
PRODUCT_NAMESPACE = os.environ.get("BALLAST_PRODUCT_NAMESPACE", "ballast")
HEALTHY_MEMORY = os.environ.get("BALLAST_HEALTHY_MEMORY", "128Mi")


class InvestigationPreflight(BaseModel):
    ready: bool
    alertname: str
    service: str
    namespace: str = DEFAULT_NAMESPACE
    alert_firing: bool = False
    alert_fired_at: str | None = None
    cluster_healthy: bool = False
    pod_state: str | None = None
    memory_limit: str | None = None
    ready_pods: int | None = None
    total_pods: int | None = None
    argocd_sync: str | None = None
    argocd_health: str | None = None
    investigation_active: bool = False
    already_investigated: bool = False
    existing_investigation_id: str | None = None
    blockers: list[str] = Field(default_factory=list)
    hint: str | None = None
    # Multi-signal incident picture
    incident_detected: bool = False
    signals: dict[str, Any] = Field(default_factory=dict)


def _service_health(service: str, namespace: str) -> dict:
    row: dict = {"service": service, "namespace": namespace}
    try:
        kube = KubernetesSource(namespace=namespace)
        crash = kube.crash_state(service)
        row["crash_state"] = crash
        row["memory_limit"] = kube.memory_limit(service)
        row["pod_state"] = crash.get("display_state")
        row["ready_pods"] = crash.get("ready_pods")
        row["total_pods"] = crash.get("pods")
        row["restarts"] = crash.get("restarts", 0)
        waiting = crash.get("waiting_reason")
        oom = crash.get("last_terminated_reason") == "OOMKilled"
        row["healthy"] = (
            row["pod_state"] == "Running"
            and not waiting
            and not oom
            and (row["ready_pods"] or 0) == (row["total_pods"] or 0)
            and (row["total_pods"] or 0) > 0
        )
    except Exception as exc:
        row["healthy"] = False
        row["pod_state"] = "Error"
        row["error"] = str(exc)
    # Deployment missing entirely — kubectl returns empty, not an exception.
    if row.get("total_pods") == 0 and not row.get("error"):
        row["healthy"] = False
        if row.get("pod_state") in (None, "Unknown", "Running", "Missing"):
            row["pod_state"] = "Missing"
    try:
        argo = ArgoCDSource().application_context(service)
        if argo:
            row["argocd_sync"] = argo.get("sync_status")
            row["argocd_health"] = argo.get("health_status")
    except Exception:
        pass
    return row


def _pending_alert(
    prom: "PrometheusSource",
    alertname: str,
    service: str | None,
    namespace: str | None,
) -> dict | None:
    """Return the alert if it is ``pending`` (inside its ``for:`` window), else None."""
    try:
        for alert in prom.active_alerts():
            if alert.get("state") != "pending":
                continue
            labels = alert.get("labels", {})
            if labels.get("alertname") != alertname:
                continue
            if service and labels.get("container") not in (service, None) and labels.get(
                "service"
            ) not in (service, None):
                continue
            if namespace and labels.get("namespace") not in (namespace, None):
                continue
            return alert
    except Exception:
        return None
    return None


def _kube_incident(
    *,
    pod_state: str | None,
    waiting: str | None,
    oom: bool,
    restarts: int,
    ready_pods: int | None,
    total_pods: int | None,
    memory_limit: str | None,
) -> tuple[bool, list[str]]:
    """Return (is_incident, reasons) from live Kubernetes state."""
    reasons: list[str] = []
    state = (pod_state or "").lower()
    if waiting == "CrashLoopBackOff" or "crashloop" in state:
        reasons.append(f"pods in CrashLoopBackOff ({restarts} restarts)")
    if oom or "oom" in state:
        reasons.append("container OOMKilled (exit 137 / lastState)")
    if total_pods and (ready_pods or 0) < total_pods and restarts > 0:
        reasons.append(f"not ready {ready_pods}/{total_pods} with restarts")
    if memory_limit and memory_limit != HEALTHY_MEMORY:
        # Demo regression signal: limit below the known-good value.
        try:
            cur = int("".join(ch for ch in memory_limit if ch.isdigit()) or "0")
            good = int("".join(ch for ch in HEALTHY_MEMORY if ch.isdigit()) or "0")
            if cur and good and cur < good:
                reasons.append(
                    f"memory limit {memory_limit} below healthy {HEALTHY_MEMORY}"
                )
        except ValueError:
            pass
    return bool(reasons), reasons


def _argocd_incident(
    *,
    sync: str | None,
    health: str | None,
    kube_bad: bool,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if health in ("Degraded", "Missing", "Suspended"):
        reasons.append(f"ArgoCD health={health}")
    if sync == "OutOfSync":
        reasons.append("ArgoCD OutOfSync")
    # Progressing alone is normal during sync; only count it with kube pain.
    if health == "Progressing" and kube_bad:
        reasons.append("ArgoCD Progressing while pods are unhealthy")
    return bool(reasons), reasons


def assess_investigation_readiness(
    alertname: str,
    service: str,
    *,
    namespace: str = DEFAULT_NAMESPACE,
) -> InvestigationPreflight:
    blockers: list[str] = []
    alert_firing = False
    alert_fired_at: str | None = None
    cluster_healthy = False
    pod_state = memory_limit = None
    ready_pods = total_pods = None
    argocd_sync = argocd_health = None
    waiting: str | None = None
    oom = False
    restarts = 0
    prom_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    signals: dict[str, Any] = {
        "prometheus": {"firing": False},
        "kubernetes": {"incident": False, "reasons": []},
        "argocd": {"incident": False, "reasons": []},
    }

    try:
        prom = PrometheusSource(prom_url)
        alert = prom.firing_alert(alertname, service=service, namespace=namespace)
        if alert:
            alert_firing = True
            alert_fired_at = alert.get("activeAt")
            signals["prometheus"] = {
                "firing": True,
                "state": "firing",
                "alertname": alertname,
                "fired_at": alert_fired_at,
            }
        else:
            # Not firing — but is it pending inside its `for:` window?
            pending = _pending_alert(prom, alertname, service, namespace)
            if pending:
                signals["prometheus"] = {
                    "firing": False,
                    "state": "pending",
                    "alertname": alertname,
                    "fired_at": pending.get("activeAt"),
                    "note": f"{alertname} pending (in for: window)",
                }
            else:
                signals["prometheus"] = {
                    "firing": False,
                    "state": "inactive",
                    "alertname": alertname,
                    "note": f"{alertname} not firing",
                }
    except Exception as exc:
        signals["prometheus"] = {"firing": False, "state": "error", "error": str(exc)}
        blockers.append(f"Prometheus unreachable: {exc}")

    kube_ok = False
    try:
        kube = KubernetesSource(namespace=namespace)
        crash = kube.crash_state(service)
        memory_limit = kube.memory_limit(service)
        pod_state = crash.get("display_state")
        ready_pods = crash.get("ready_pods")
        total_pods = crash.get("pods")
        waiting = crash.get("waiting_reason")
        oom = crash.get("last_terminated_reason") == "OOMKilled" or crash.get(
            "exit_code"
        ) == 137
        restarts = int(crash.get("restarts") or 0)
        kube_ok = total_pods is not None
        cluster_healthy = (
            pod_state == "Running"
            and not waiting
            and not oom
            and (ready_pods or 0) > 0
            and (ready_pods or 0) == (total_pods or 0)
        )
        kube_bad, kube_reasons = _kube_incident(
            pod_state=pod_state,
            waiting=waiting,
            oom=oom,
            restarts=restarts,
            ready_pods=ready_pods,
            total_pods=total_pods,
            memory_limit=memory_limit,
        )
        signals["kubernetes"] = {
            "incident": kube_bad,
            "reasons": kube_reasons,
            "pod_state": pod_state,
            "memory_limit": memory_limit,
            "ready_pods": ready_pods,
            "total_pods": total_pods,
            "restarts": restarts,
            "waiting_reason": waiting,
            "oom_killed": oom,
        }
    except Exception as exc:
        kube_bad = False
        blockers.append(f"Kubernetes unreachable: {exc}")
        signals["kubernetes"] = {"incident": False, "error": str(exc)}

    try:
        argo = ArgoCDSource().application_context(service)
        if argo:
            argocd_sync = argo.get("sync_status")
            argocd_health = argo.get("health_status")
            argo_bad, argo_reasons = _argocd_incident(
                sync=argocd_sync, health=argocd_health, kube_bad=kube_bad
            )
            signals["argocd"] = {
                "incident": argo_bad,
                "reasons": argo_reasons,
                "sync_status": argocd_sync,
                "health_status": argocd_health,
                "revision": argo.get("revision"),
                "last_sync_finished": argo.get("last_sync_finished"),
            }
        else:
            signals["argocd"] = {"incident": False, "note": "application not found"}
    except Exception as exc:
        signals["argocd"] = {"incident": False, "error": str(exc)}

    # False positive: alert alone while pods look fine.
    if alert_firing and kube_ok and cluster_healthy:
        blockers.append(
            f"{service} pods are Running but {alertname} is firing — confirm in Prometheus"
        )

    kube_signal = bool(signals["kubernetes"].get("incident"))
    argo_signal = bool(signals["argocd"].get("incident"))
    incident_detected = bool(alert_firing or kube_signal or argo_signal)

    investigation_active = False
    existing_id: str | None = None
    active = STORE.find_active_for_alert(alertname, service)
    if active:
        investigation_active = True
        existing_id = active.id
        blockers.append(f"Investigation already running for {alertname}/{service}")

    already_investigated = False
    episode_ts = alert_fired_at
    if not episode_ts and kube_signal:
        # Dedup without an alert: reuse recent investigation for same service.
        recent = STORE.find_recent_for_service(service, within_seconds=3600)
        if recent and recent.status.value == "complete":
            already_investigated = True
            existing_id = recent.id
            blockers.append(
                "A recent investigation for this service already completed — see the sidebar"
            )
    if alert_firing and alert_fired_at:
        already_investigated = STORE.has_for_alert_episode(
            alertname, service, alert_fired_at
        )
        if already_investigated and not investigation_active:
            existing = STORE.find_for_alert_episode(alertname, service, alert_fired_at)
            existing_id = existing.id if existing else existing_id
            blockers.append(
                "This alert episode was already investigated — see the existing run in the sidebar"
            )

    # Console triggers without a firing alert carry a fresh `_now()` episode, so
    # episode-exact dedup above misses a run that already exists for this same
    # incident. Fall back to any recent run for this alert+service so preflight
    # reports it as already-investigated (ready=False, existing id surfaced) and
    # the console points the operator at it instead of spawning a duplicate —
    # matching the idempotency `_start` now enforces on the write path.
    if not investigation_active and not already_investigated:
        recent = STORE.find_recent_for_alert(alertname, service)
        if recent is not None:
            already_investigated = True
            existing_id = recent.id
            blockers.append(
                "A recent investigation already exists for this incident — see the sidebar"
            )

    false_positive = alert_firing and kube_ok and cluster_healthy
    ready = (
        incident_detected
        and not investigation_active
        and not already_investigated
        and not false_positive
    )

    # Drop "alert not firing" as a hard blocker when kube/argo already show pain.
    if incident_detected and not alert_firing:
        blockers = [
            b
            for b in blockers
            if "is not firing" not in b and "Prometheus unreachable" not in b
        ]

    reasons = []
    if alert_firing:
        reasons.append(f"Prometheus `{alertname}` firing")
    reasons.extend(signals["kubernetes"].get("reasons") or [])
    reasons.extend(signals["argocd"].get("reasons") or [])

    if investigation_active and existing_id:
        hint = f"Investigation already in progress — open `{existing_id}` in the sidebar."
    elif already_investigated and existing_id:
        hint = f"Already investigated this episode — open `{existing_id}` in the sidebar."
    elif ready:
        hint = (
            "Incident signals detected ("
            + "; ".join(reasons[:3])
            + ") — starting multi-signal investigation (Kubernetes + ArgoCD + Prometheus)."
        )
    elif not incident_detected and cluster_healthy:
        hint = (
            "Everything looks good across Kubernetes, ArgoCD, and Prometheus. "
            "Run `task break` to induce the demo incident."
        )
    elif not incident_detected:
        hint = (
            "No clear incident signals yet. Run `task break` to induce CrashLoop / OOM, "
            f"or wait for `{alertname}`."
        )
    else:
        hint = blockers[0] if blockers else None

    return InvestigationPreflight(
        ready=ready,
        alertname=alertname,
        service=service,
        namespace=namespace,
        alert_firing=alert_firing,
        alert_fired_at=alert_fired_at,
        cluster_healthy=cluster_healthy,
        pod_state=pod_state,
        memory_limit=memory_limit,
        ready_pods=ready_pods,
        total_pods=total_pods,
        argocd_sync=argocd_sync,
        argocd_health=argocd_health,
        investigation_active=investigation_active,
        already_investigated=already_investigated,
        existing_investigation_id=existing_id,
        blockers=blockers,
        hint=hint,
        incident_detected=incident_detected,
        signals=signals,
    )


def cluster_overview(primary_service: str = "ingest") -> dict:
    namespace = DEFAULT_NAMESPACE
    prom_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    firing_alerts: list[dict] = []
    infra_alerts: list[dict] = []
    ballast_firing = False
    prom_error: str | None = None

    try:
        prom = PrometheusSource(prom_url)
        for alert in prom.active_alerts():
            if alert.get("state") != "firing":
                continue
            labels = alert.get("labels", {})
            row = {
                "alertname": labels.get("alertname"),
                "service": labels.get("container") or labels.get("service"),
                "namespace": labels.get("namespace"),
                "severity": labels.get("severity"),
            }
            aname = labels.get("alertname") or ""
            if labels.get("namespace") == namespace or aname.startswith(
                ("StreamIngest", "Ballast")
            ):
                firing_alerts.append(row)
            else:
                infra_alerts.append(row)
            if labels.get("alertname") == DEFAULT_ALERT:
                if labels.get("namespace") in (namespace, None):
                    svc = labels.get("container") or labels.get("service")
                    if svc in (primary_service, None):
                        ballast_firing = True
    except Exception as exc:
        prom_error = str(exc)

    services = [_service_health(svc, namespace) for svc in BALLAST_SERVICES]
    argocd_primary: dict | None = None
    try:
        argocd_primary = ArgoCDSource().application_context(primary_service)
    except Exception:
        pass

    preflight = assess_investigation_readiness(
        DEFAULT_ALERT, primary_service, namespace=namespace
    )
    all_services_healthy = all(s.get("healthy") for s in services if "error" not in s)
    argocd_ok = True
    if argocd_primary:
        argo_health = argocd_primary.get("health_status")
        argo_sync = argocd_primary.get("sync_status")
        if argo_health in ("Degraded", "Missing", "Suspended"):
            argocd_ok = False
        elif argo_sync == "OutOfSync":
            argocd_ok = False

    return {
        "primary_service": primary_service,
        "namespace": namespace,
        "demo_namespace": namespace,
        "product_namespace": PRODUCT_NAMESPACE,
        "healthy": all_services_healthy
        and not ballast_firing
        and argocd_ok
        and not preflight.incident_detected,
        "investigation_ready": preflight.ready,
        "incident_detected": preflight.incident_detected,
        "signals": preflight.signals,
        "firing_alert_count": len(firing_alerts),
        "infra_alert_count": len(infra_alerts),
        "ballast_alert_firing": ballast_firing,
        "firing_alerts": firing_alerts[:20],
        "infra_alerts": infra_alerts[:20],
        "prometheus_error": prom_error,
        "services": services,
        "argocd": argocd_primary,
        "preflight": preflight.model_dump(),
    }
