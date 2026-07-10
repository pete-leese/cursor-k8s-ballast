"""HTML snapshot of Prometheus firing alerts (for PNG rendering)."""

from __future__ import annotations

import html as html_lib
from typing import Any

from .prometheus_evidence import prometheus_alerts_url

_SNAPSHOT_CSS = """
  body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; background: #f8fafc; }
  .prom-snap {
    border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden;
    background: #fff; margin: 12px; font-size: 14px; max-width: 760px;
  }
  .prom-snap-head {
    padding: 12px 16px; background: #e85d04; color: #fff;
    font-weight: 700; font-size: 15px;
  }
  .prom-snap-sub {
    padding: 8px 16px; background: #fff7ed; color: #9a3412;
    font-size: 12px; border-bottom: 1px solid #fed7aa;
  }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th {
    text-align: left; padding: 10px 12px; background: #f1f5f9;
    color: #475569; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
  }
  td { padding: 10px 12px; border-top: 1px solid #f1f5f9; color: #334155; vertical-align: top; }
  .state-firing {
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    background: #fee2e2; color: #b91c1c; font-size: 11px; font-weight: 700;
  }
  code { font-family: ui-monospace, Menlo, monospace; font-size: 11px; color: #64748b; }
  .prom-foot { padding: 10px 16px; font-size: 11px; color: #94a3b8; border-top: 1px solid #f1f5f9; }
"""


def _alert_row(alert: dict[str, Any]) -> str:
    labels = alert.get("labels") or {}
    name = html_lib.escape(labels.get("alertname", "—"))
    state = html_lib.escape(alert.get("state", "firing"))
    active = html_lib.escape(alert.get("activeAt", "—"))
    label_bits = " ".join(
        f'<code>{html_lib.escape(k)}={html_lib.escape(v)}</code>'
        for k, v in sorted(labels.items())
        if k != "alertname"
    )
    ann = alert.get("annotations") or {}
    summary = ann.get("summary") or ann.get("description") or ""
    summary_html = (
        f'<div style="margin-top:4px;font-size:12px;color:#64748b">'
        f"{html_lib.escape(summary)}</div>"
        if summary
        else ""
    )
    return (
        f"<tr><td><strong>{name}</strong>{summary_html}</td>"
        f'<td><span class="state-firing">{state}</span></td>'
        f"<td>{active}</td><td>{label_bits or '—'}</td></tr>"
    )


def prometheus_snapshot_html(
    alert: Any,
    *,
    firing_alerts: list[dict[str, Any]] | None = None,
) -> str:
    """Return alerts table markup (body fragment)."""
    rows = ""
    if firing_alerts:
        for a in firing_alerts:
            if a.get("state") == "firing":
                rows += _alert_row(a)
    if not rows and alert is not None:
        if hasattr(alert, "model_dump"):
            labels = alert.labels
            rows = _alert_row(
                {
                    "state": "firing",
                    "activeAt": alert.fired_at,
                    "labels": {"alertname": alert.alertname, **labels},
                    "annotations": {"description": alert.expr or ""},
                }
            )
        else:
            rows = _alert_row(alert)
    if not rows:
        rows = "<tr><td colspan='4'>No firing alerts captured</td></tr>"

    link = html_lib.escape(prometheus_alerts_url())
    return (
        f'<div class="prom-snap">'
        f'<div class="prom-snap-head">Prometheus · Alerts</div>'
        f'<div class="prom-snap-sub">state=firing</div>'
        f"<table><thead><tr>"
        f"<th>Alert</th><th>State</th><th>Active at</th><th>Labels</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
        f'<div class="prom-foot">Captured from Prometheus API · {link}</div>'
        f"</div>"
    )


def prometheus_snapshot_document(
    alert: Any,
    *,
    firing_alerts: list[dict[str, Any]] | None = None,
) -> str:
    body = prometheus_snapshot_html(alert, firing_alerts=firing_alerts)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{_SNAPSHOT_CSS}</style></head><body>{body}</body></html>"
    )
