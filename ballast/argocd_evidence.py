"""ArgoCD evidence helpers for RCA enrichment and console deeplinks."""

from __future__ import annotations

import os

from .brief import ArgoCDContext, InvestigationBrief
from .contract import Evidence, EvidenceSource, RCA
from .evidence_attach import artifact_url, attach_screenshot_to_evidence


def argocd_ui_url(service: str) -> str:
    """Deep link to the ArgoCD application page (local port-forward by default).

    Argo CD 2.8+/3.x routes are ``/applications/{namespace}/{name}`` (the
    Application CR namespace), not ``/applications/{project}/{name}``. Using the
    project slug here yields a logged-in "permission denied" empty page.
    """
    base = os.environ.get("ARGOCD_URL", "").rstrip("/")
    if base:
        return base
    port = os.environ.get("ARGOCD_PORT", "8080")
    namespace = os.environ.get("ARGOCD_APP_NAMESPACE", "argocd")
    return f"https://localhost:{port}/applications/{namespace}/{service}"


def attach_screenshot_to_argocd_evidence(rca: RCA, screenshot_url: str) -> RCA:
    return attach_screenshot_to_evidence(
        rca,
        EvidenceSource.argocd,
        screenshot_url,
        fallback_detail="ArgoCD application state at time of investigation.",
    )


def _field(ctx: ArgoCDContext | dict, name: str, default=None):
    if isinstance(ctx, ArgoCDContext):
        return getattr(ctx, name, default)
    return ctx.get(name, default)


def argocd_evidence_items(ctx: ArgoCDContext | dict, service: str) -> list[Evidence]:
    """Build contract evidence rows from triage or live ArgoCD application state."""
    if not ctx:
        return []

    application = _field(ctx, "application") or service
    sync = _field(ctx, "sync_status") or "unknown"
    health = _field(ctx, "health_status") or "unknown"
    revision = _field(ctx, "revision")
    target = _field(ctx, "target_revision")
    phase = _field(ctx, "last_sync_phase")
    message = _field(ctx, "last_sync_message")
    finished = _field(ctx, "last_sync_finished")
    deeplink = argocd_ui_url(service)

    parts = [f"ArgoCD application `{application}`: sync={sync}, health={health}"]
    if revision:
        parts.append(f"live revision `{revision[:12]}`")
    if target:
        parts.append(f"tracking `{target}`")
    if phase:
        parts.append(f"last operation {phase}")
    if finished:
        parts.append(f"finished {finished}")

    items = [
        Evidence(
            source=EvidenceSource.argocd,
            detail="; ".join(parts) + ".",
            deeplink=deeplink,
        )
    ]

    if message:
        items.append(
            Evidence(
                source=EvidenceSource.argocd,
                detail=f"Sync operation message: {message}",
                deeplink=deeplink,
            )
        )

    resources = _field(ctx, "sync_resources") or []
    for res in resources:
        if isinstance(res, dict):
            kind, name = res.get("kind"), res.get("name")
            status, res_msg = res.get("status"), res.get("message")
        else:
            kind, name = res.kind, res.name
            status, res_msg = res.status, res.message
        if kind == "Deployment" or status in ("SyncFailed", "Failed"):
            detail = f"Resource {kind}/{name}: {status or '—'}"
            if res_msg:
                detail += f" — {res_msg}"
            items.append(
                Evidence(
                    source=EvidenceSource.argocd,
                    detail=detail,
                    deeplink=deeplink,
                )
            )
            break

    for ev in (_field(ctx, "events") or [])[:1]:
        if isinstance(ev, dict):
            reason, ev_msg = ev.get("reason"), ev.get("message")
        else:
            reason, ev_msg = ev.reason, ev.message
        if reason and ev_msg:
            items.append(
                Evidence(
                    source=EvidenceSource.argocd,
                    detail=f"Cluster event {reason}: {ev_msg}",
                    deeplink=deeplink,
                )
            )

    return items


def enrich_rca_with_argocd(rca: RCA, brief: InvestigationBrief) -> RCA:
    """Append ArgoCD evidence from the triage brief when the investigator omitted it."""
    if brief.argocd is None:
        return rca
    if any(e.source == EvidenceSource.argocd for e in rca.evidence):
        return rca
    extra = argocd_evidence_items(brief.argocd, brief.service)
    if not extra:
        return rca
    return rca.model_copy(update={"evidence": [*rca.evidence, *extra]})
