"""Prometheus alerts URL and evidence helpers."""

from __future__ import annotations

import os

from .brief import AlertContext
from .contract import Evidence, EvidenceSource, RCA
from .evidence_attach import attach_screenshot_to_evidence


def prometheus_alerts_url(*, state: str = "firing") -> str:
    """Deep link to the Prometheus alerts UI (local port-forward by default)."""
    custom = os.environ.get("PROMETHEUS_ALERTS_URL", "").rstrip("/")
    if custom:
        return custom
    base = os.environ.get("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
    return f"{base}/alerts?state={state}"


def attach_screenshot_to_prometheus_evidence(rca: RCA, screenshot_url: str) -> RCA:
    return attach_screenshot_to_evidence(
        rca,
        EvidenceSource.prometheus,
        screenshot_url,
        fallback_detail="Prometheus firing alerts at time of investigation.",
    )


def prometheus_evidence_from_alert(alert: AlertContext, service: str) -> Evidence:
    labels = ", ".join(f"{k}={v}" for k, v in sorted(alert.labels.items()))
    detail = (
        f"{alert.alertname} firing for {service} since {alert.fired_at}"
        + (f" (severity={alert.severity})" if alert.severity else "")
        + (f"; labels: {labels}" if labels else "")
        + "."
    )
    return Evidence(
        source=EvidenceSource.prometheus,
        detail=detail,
        deeplink=prometheus_alerts_url(),
    )
