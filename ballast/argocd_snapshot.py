"""HTML snapshot of an ArgoCD application panel (for PNG rendering)."""

from __future__ import annotations

import html as html_lib

from .argocd_evidence import argocd_ui_url

_SNAPSHOT_CSS = """
  body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; background: #f1f5f9; }
  .ballast-argocd-snap {
    border: 1px solid #d1d5db; border-radius: 10px; overflow: hidden;
    background: #fff; margin: 12px; font-size: 14px; max-width: 680px;
  }
  .ballast-argocd-snap-head {
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    padding: 12px 16px; background: #1e293b; color: #f8fafc;
  }
  .ballast-argocd-snap-title { font-weight: 700; font-size: 15px; }
  .ballast-argocd-snap-badges { display: flex; gap: 6px; flex-wrap: wrap; }
  .ballast-argocd-badge {
    padding: 2px 10px; border-radius: 999px; font-size: 11px; font-weight: 700;
  }
  .ballast-argocd-snap-body { padding: 14px 16px; color: #334155; }
  .ballast-argocd-meta {
    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 16px;
    margin-bottom: 12px; font-size: 12px; color: #64748b;
  }
  .ballast-argocd-meta strong { color: #0f172a; font-weight: 600; }
  .ballast-argocd-msg {
    font-size: 13px; color: #475569; background: #f8fafc;
    border-left: 3px solid #cbd5e1; padding: 10px 12px;
    border-radius: 0 6px 6px 0; line-height: 1.45; margin-bottom: 12px;
  }
  .ballast-argocd-resource {
    display: flex; align-items: center; gap: 8px; padding: 8px 0;
    border-top: 1px solid #f1f5f9; font-size: 13px;
  }
  code { font-family: ui-monospace, Menlo, monospace; font-size: 12px; }
"""


def _badge(label: str, bg: str, fg: str = "#fff") -> str:
    return (
        f'<span class="ballast-argocd-badge" style="background:{bg};color:{fg}">'
        f"{html_lib.escape(label)}</span>"
    )


def argocd_snapshot_html(argo: dict, service: str, *, ui_url: str | None = None) -> str:
    """Return the application panel markup (body fragment)."""
    app_name = html_lib.escape(argo.get("application") or service)
    sync = argo.get("sync_status") or "—"
    health = argo.get("health_status") or "—"
    sync_color = {"Synced": "#15803d", "OutOfSync": "#b45309"}.get(sync, "#475569")
    health_color = {
        "Healthy": "#15803d",
        "Degraded": "#b91c1c",
        "Progressing": "#1d4ed8",
    }.get(health, "#475569")
    revision = html_lib.escape((argo.get("revision") or "—")[:12])
    target = html_lib.escape(argo.get("target_revision") or "—")
    phase = html_lib.escape(argo.get("last_sync_phase") or "—")
    finished = html_lib.escape(argo.get("last_sync_finished") or "—")
    message = argo.get("last_sync_message")
    link = html_lib.escape(ui_url or argocd_ui_url(service))

    resources_html = ""
    for res in argo.get("sync_resources") or []:
        if res.get("kind") != "Deployment":
            continue
        status = res.get("status") or "—"
        res_color = {"Synced": "#15803d", "Failed": "#b91c1c"}.get(status, "#475569")
        resources_html = (
            f'<div class="ballast-argocd-resource">'
            f"{_badge(status, res_color)} "
            f"<span><strong>{html_lib.escape(res.get('kind') or '')}</strong> "
            f"<code>{html_lib.escape(res.get('name') or '')}</code></span></div>"
        )
        if res.get("message"):
            resources_html += (
                f'<div style="font-size:12px;color:#64748b;padding:0 0 8px 0">'
                f"{html_lib.escape(res['message'])}</div>"
            )
        break

    msg_html = ""
    if message:
        msg_html = f'<div class="ballast-argocd-msg">{html_lib.escape(message)}</div>'

    open_link = ""
    if link:
        open_link = (
            f'<div style="margin-top:10px;font-size:11px;color:#64748b">'
            f"Captured from cluster API · {link}</div>"
        )

    return (
        f'<div class="ballast-argocd-snap">'
        f'<div class="ballast-argocd-snap-head">'
        f'<span class="ballast-argocd-snap-title">APPLICATIONS / {app_name}</span>'
        f'<span class="ballast-argocd-snap-badges">'
        f"{_badge(sync, sync_color)}{_badge(health, health_color)}"
        f"</span></div>"
        f'<div class="ballast-argocd-snap-body">'
        f'<div class="ballast-argocd-meta">'
        f"<div>Revision <strong>{revision}</strong></div>"
        f"<div>Target <strong>{target}</strong></div>"
        f"<div>Last op <strong>{phase}</strong></div>"
        f"<div>Finished <strong>{finished}</strong></div>"
        f"</div>{msg_html}{resources_html}{open_link}"
        f"</div></div>"
    )


def argocd_snapshot_document(argo: dict, service: str) -> str:
    """Full HTML document for headless browser screenshot."""
    body = argocd_snapshot_html(argo, service)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{_SNAPSHOT_CSS}</style></head><body>{body}</body></html>"
    )
