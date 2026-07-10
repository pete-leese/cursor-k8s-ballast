"""Pre-investigation and cluster health checks."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from .sources import ArgoCDSource, KubernetesSource, PrometheusSource
from .store import STORE

BALLAST_SERVICES = ["payments", "checkout", "orders", "notifications", "ledger"]
DEFAULT_ALERT = os.environ.get("BALLAST_ALERTNAME", "BallastServiceCrashLooping")
DEFAULT_NAMESPACE = os.environ.get("BALLAST_NAMESPACE", "ballast")


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
        row["error"] = str(exc)
    try:
        argo = ArgoCDSource().application_context(service)
        if argo:
            row["argocd_sync"] = argo.get("sync_status")
            row["argocd_health"] = argo.get("health_status")
    except Exception:
        pass
    return row


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
    prom_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

    try:
        prom = PrometheusSource(prom_url)
        alert = prom.firing_alert(alertname, service=service, namespace=namespace)
        if alert:
            alert_firing = True
            alert_fired_at = alert.get("activeAt")
        else:
            blockers.append(f"{alertname} is not firing for {service}")
    except Exception as exc:
        blockers.append(f"Prometheus unreachable: {exc}")

    kube_ok = False
    try:
        kube = KubernetesSource(namespace=namespace)
        crash = kube.crash_state(service)
        memory_limit = kube.memory_limit(service)
        pod_state = crash.get("display_state")
        ready_pods = crash.get("ready_pods")
        total_pods = crash.get("pods")
        kube_ok = total_pods is not None
        waiting = crash.get("waiting_reason")
        oom = crash.get("last_terminated_reason") == "OOMKilled"
        cluster_healthy = (
            pod_state == "Running"
            and not waiting
            and not oom
            and (ready_pods or 0) > 0
            and (ready_pods or 0) == (total_pods or 0)
        )
        if alert_firing and kube_ok and cluster_healthy:
            blockers.append(
                f"{service} pods are Running but {alertname} is firing — confirm in Prometheus"
            )
    except Exception as exc:
        blockers.append(f"Kubernetes unreachable: {exc}")

    try:
        argo = ArgoCDSource().application_context(service)
        if argo:
            argocd_sync = argo.get("sync_status")
            argocd_health = argo.get("health_status")
    except Exception:
        pass

    investigation_active = STORE.has_active_for_alert(alertname, service)
    if investigation_active:
        blockers.append(f"Investigation already running for {alertname}/{service}")

    already_investigated = False
    existing_id: str | None = None
    if alert_firing and alert_fired_at:
        already_investigated = STORE.has_for_alert_episode(
            alertname, service, alert_fired_at
        )
        if already_investigated and not investigation_active:
            existing = STORE.find_for_alert_episode(alertname, service, alert_fired_at)
            existing_id = existing.id if existing else None
            blockers.append(
                "This alert episode was already investigated — see the existing run in the sidebar"
            )

    cluster_blocks = alert_firing and kube_ok and cluster_healthy
    ready = (
        alert_firing
        and not investigation_active
        and not already_investigated
        and not cluster_blocks
    )

    if not alert_firing and cluster_healthy:
        hint = "Everything looks good — no firing alerts and workloads are healthy."
    elif not alert_firing:
        hint = f"No active incident detected. Run `task break` to induce the demo, or wait for {alertname}."
    elif already_investigated and existing_id:
        hint = f"Already investigated this episode — open `{existing_id}` in the sidebar."
    elif ready:
        hint = "Incident detected — starting deep investigation (RCA, evidence, auto-fix PR)."
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
    )


def cluster_overview(primary_service: str = "payments") -> dict:
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
            # Scope the headline count to alerts about the Ballast demo's own
            # workloads — a kind cluster fires plenty of unrelated infra noise
            # (Watchdog heartbeat, control-plane TargetDown, etcd, clock skew)
            # that would otherwise make "firing alerts" look misleadingly high.
            if labels.get("namespace") == namespace or (
                labels.get("alertname") or ""
            ).startswith("Ballast"):
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
    argocd_ok = (
        (argocd_primary or {}).get("sync_status") == "Synced"
        and (argocd_primary or {}).get("health_status") == "Healthy"
    )

    return {
        "primary_service": primary_service,
        "namespace": namespace,
        "healthy": all_services_healthy and not ballast_firing and argocd_ok,
        "investigation_ready": preflight.ready,
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
