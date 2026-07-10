"""Shared helpers for attaching evidence screenshots to RCAs."""

from __future__ import annotations

import os

from .contract import Evidence, EvidenceSource, RCA


def artifact_url(investigation_id: str, name: str) -> str:
    base = os.environ.get(
        "BALLAST_PUBLIC_API_URL",
        os.environ.get("BALLAST_API_URL", "http://localhost:8000"),
    )
    return f"{base.rstrip('/')}/investigations/{investigation_id}/artifacts/{name}"


def attach_screenshot_to_evidence(
    rca: RCA,
    source: EvidenceSource,
    screenshot_url: str,
    *,
    fallback_detail: str,
) -> RCA:
    """Set screenshot_url on the first evidence row for the given source."""
    if not screenshot_url:
        return rca
    updated: list[Evidence] = []
    attached = False
    for ev in rca.evidence:
        if ev.source == source and not attached:
            ev = ev.model_copy(update={"screenshot_url": screenshot_url})
            attached = True
        updated.append(ev)
    if not attached:
        updated.insert(
            0,
            Evidence(
                source=source,
                detail=fallback_detail,
                deeplink=None,
                screenshot_url=screenshot_url,
            ),
        )
    return rca.model_copy(update={"evidence": updated})
