"""Triage + investigation orchestration for the Ballast console API."""

from __future__ import annotations

import os
from pathlib import Path

from .brief import AlertContext, RepoTarget
from .engine import assemble_brief
from .investigator import get_investigator
from .sources import KubernetesSource, PrometheusSource
from .store import STORE, InvestigationStatus
from .topology import DeclaredTopologySource

_ROOT = Path(__file__).resolve().parent.parent


def run_investigation(
    investigation_id: str,
    alert: AlertContext,
    service: str,
    *,
    namespace: str = "ballast",
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
        try:
            prom = PrometheusSource(prom_url)
        except Exception:
            pass
        try:
            kube = KubernetesSource(namespace=namespace)
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

        investigator = get_investigator()
        produced_rca = False
        for event in investigator.investigate(brief):
            STORE.append_event(investigation_id, event)
            if event.type == "rca" and event.rca is not None:
                STORE.update(investigation_id, rca=event.rca)
                produced_rca = True
            elif event.type == "error":
                STORE.update(investigation_id, error=event.text)

        STORE.update(
            investigation_id,
            status=InvestigationStatus.complete
            if produced_rca
            else InvestigationStatus.failed,
        )
    except Exception as exc:
        STORE.update(
            investigation_id,
            status=InvestigationStatus.failed,
            error=str(exc),
        )
