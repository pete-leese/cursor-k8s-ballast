"""Triage + investigation orchestration for the Ballast console API."""

from __future__ import annotations

import os
from pathlib import Path

from .argocd_evidence import (
    attach_screenshot_to_argocd_evidence,
    enrich_rca_with_argocd,
)
from .brief import AlertContext, RepoTarget
from .engine import assemble_brief
from .evidence_attach import artifact_url
from .investigator import get_investigator
from .prometheus_evidence import (
    attach_screenshot_to_prometheus_evidence,
    prometheus_evidence_from_alert,
)
from .remediate import should_auto_remediate, spawn_remediation
from .screenshot import (
    capture_argocd_evidence_png,
    capture_grafana_evidence_png,
    capture_prometheus_evidence_png,
    grafana_dashboard_url,
)
from .sources import ArgoCDSource, KubernetesSource, PrometheusSource
from .store import STORE, InvestigationStatus
from .topology import DeclaredTopologySource
from .contract import Evidence, EvidenceSource

_ROOT = Path(__file__).resolve().parent.parent


def run_investigation(
    investigation_id: str,
    alert: AlertContext,
    service: str,
    *,
    namespace: str = "demo",
    healthy_memory: str | None = None,
    repo: RepoTarget | None = None,
) -> None:
    try:
        healthy = healthy_memory or os.environ.get("BALLAST_HEALTHY_MEMORY", "128Mi")
        repo = repo or RepoTarget(
            url=os.environ.get(
                "CURSOR_TARGET_REPO",
                "https://github.com/pete-leese/cursor-k8s-ballast",
            ),
            ref=os.environ.get("CURSOR_TARGET_REF", "main"),
            chart_path="charts/ballast-service",
        )
        prom_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
        topology = DeclaredTopologySource(_ROOT / "topology.yaml")

        STORE.update(investigation_id, status=InvestigationStatus.triaging)

        prom: PrometheusSource | None = None
        kube: KubernetesSource | None = None
        argo: ArgoCDSource | None = None
        try:
            prom = PrometheusSource(prom_url)
        except Exception:
            pass
        try:
            kube = KubernetesSource(namespace=namespace)
        except Exception:
            pass
        try:
            argo = ArgoCDSource()
        except Exception:
            pass

        brief = assemble_brief(
            investigation_id=investigation_id,
            service=service,
            namespace=namespace,
            prometheus=prom,
            kubernetes=kube,
            topology=topology,
            healthy_memory=healthy,
            repo_url=repo.url,
            repo_ref=repo.ref,
            alertname=alert.alertname,
            argocd=argo,
        )
        if alert.fired_at:
            brief.alert.fired_at = alert.fired_at
        if alert.expr:
            brief.alert.expr = alert.expr
        if alert.severity:
            brief.alert.severity = alert.severity
        if alert.labels:
            brief.alert.labels = alert.labels

        STORE.update(
            investigation_id,
            brief=brief,
            status=InvestigationStatus.investigating,
        )

        screenshot_url: str | None = None
        prom_screenshot_url: str | None = None
        grafana_screenshot_url: str | None = None

        argo_for_shot = brief.argocd
        if argo_for_shot is None and argo is not None:
            try:
                raw = argo.application_context(brief.service)
                if raw:
                    argo_for_shot = raw
            except Exception:
                pass
        if argo_for_shot is not None:
            png = capture_argocd_evidence_png(argo_for_shot, brief.service)
            if png:
                STORE.put_artifact(investigation_id, "argocd.png", png)
                screenshot_url = artifact_url(investigation_id, "argocd.png")

        firing_alerts: list[dict] | None = None
        if prom is not None:
            try:
                firing_alerts = prom.active_alerts()
            except Exception:
                firing_alerts = None
        prom_png = capture_prometheus_evidence_png(
            brief.alert, firing_alerts=firing_alerts
        )
        if prom_png:
            STORE.put_artifact(investigation_id, "prometheus.png", prom_png)
            prom_screenshot_url = artifact_url(investigation_id, "prometheus.png")

        grafana_png = capture_grafana_evidence_png(brief.service)
        if grafana_png:
            STORE.put_artifact(investigation_id, "grafana.png", grafana_png)
            grafana_screenshot_url = artifact_url(investigation_id, "grafana.png")

        investigator = get_investigator()
        produced_rca = False
        final_rca = None
        for event in investigator.investigate(brief):
            STORE.append_event(investigation_id, event)
            if event.name and str(event.name).startswith("bc-"):
                STORE.update(investigation_id, cursor_agent_id=event.name)
            if event.type == "rca" and event.rca is not None:
                rca = enrich_rca_with_argocd(event.rca, brief)
                if screenshot_url:
                    rca = attach_screenshot_to_argocd_evidence(rca, screenshot_url)
                if prom_screenshot_url:
                    if not any(e.source.value == "prometheus" for e in rca.evidence):
                        rca = rca.model_copy(
                            update={
                                "evidence": [
                                    prometheus_evidence_from_alert(
                                        brief.alert, brief.service
                                    ),
                                    *rca.evidence,
                                ]
                            }
                        )
                    rca = attach_screenshot_to_prometheus_evidence(
                        rca, prom_screenshot_url
                    )
                if grafana_screenshot_url:
                    grafana_link = grafana_dashboard_url(brief.service)
                    rca = rca.model_copy(
                        update={
                            "evidence": [
                                *rca.evidence,
                                Evidence(
                                    source=EvidenceSource.prometheus,
                                    detail=(
                                        f"Grafana Ballast RCA dashboard for {brief.service} "
                                        "captured at investigation time "
                                        "(CrashLoop / OOM / memory vs limit)."
                                    ),
                                    deeplink=grafana_link,
                                    screenshot_url=grafana_screenshot_url,
                                ),
                            ]
                        }
                    )
                STORE.update(investigation_id, rca=rca)
                produced_rca = True
                final_rca = rca
            elif event.type == "error":
                STORE.update(investigation_id, error=event.text)

        STORE.update(
            investigation_id,
            status=InvestigationStatus.complete
            if produced_rca
            else InvestigationStatus.failed,
        )
        if produced_rca and final_rca is not None and should_auto_remediate(final_rca):
            STORE.update(investigation_id, remediation_status="queued")
            spawn_remediation(investigation_id, final_rca)
    except Exception as exc:
        STORE.update(
            investigation_id,
            status=InvestigationStatus.failed,
            error=str(exc),
        )
