"""Ballast console — enterprise RCA investigation view.

Sidebar: investigation list and actions.
Main: tabbed full-width workspace (Timeline · GitOps · Investigation · Root cause).

Reads from the Ballast API (BALLAST_API_URL).
"""

from __future__ import annotations

import os
import time
import html as html_lib
from datetime import datetime

import requests
import streamlit as st

from theme import badge_inline, html_panel, inject_styles, pane_title, streamlit_badge_color

API = os.environ.get("BALLAST_API_URL", "http://localhost:8000")
RUNNING = {"queued", "triaging", "investigating"}

# Palette
BLUE, GREEN, RED, AMBER, SLATE, INDIGO, TEAL = (
    "#1d4ed8",
    "#15803d",
    "#b91c1c",
    "#b45309",
    "#475569",
    "#4338ca",
    "#0f766e",
)
STATUS_COLOR = {
    "complete": GREEN,
    "failed": RED,
    "queued": SLATE,
    "triaging": AMBER,
    "investigating": AMBER,
    "Synced": GREEN,
    "OutOfSync": AMBER,
    "Healthy": GREEN,
    "Degraded": RED,
    "Progressing": BLUE,
    "Missing": RED,
    "Succeeded": GREEN,
    "Failed": RED,
}
ACTION_COLOR = {
    "rollback": RED,
    "forward_fix": BLUE,
    "staged_rollout": AMBER,
    "investigate_more": SLATE,
}
EVENT_COLOR = {
    "status": SLATE,
    "thinking": INDIGO,
    "tool_call": BLUE,
    "assistant": TEAL,
    "error": RED,
    "rca": GREEN,
}
KIND_COLOR = {
    "alert": RED,
    "rollout": BLUE,
    "chart_bump": INDIGO,
    "crashloop": RED,
    "note": SLATE,
    "argocd": TEAL,
    "investigation": INDIGO,
}

st.set_page_config(page_title="Ballast", layout="wide", page_icon="⚓")
inject_styles()


def badge(text: str, color: str) -> str:
    return badge_inline(text, color)


def conf_color(score: float) -> str:
    return GREEN if score >= 0.8 else AMBER if score >= 0.5 else RED


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def fmt_dt(value: str | None) -> str:
    dt = parse_ts(value)
    if not dt:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def fmt_time(value: str | None) -> str:
    dt = parse_ts(value)
    if not dt:
        return "—"
    return dt.strftime("%H:%M:%S")


def short_rev(value: str | None, n: int = 8) -> str:
    if not value:
        return "—"
    return value[:n]


def api_get(path: str):
    try:
        r = requests.get(f"{API}{path}", timeout=8)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.session_state["api_error"] = str(exc)
        return None


def api_post(path: str, body: dict | None = None):
    try:
        r = requests.post(f"{API}{path}", json=body or {}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


def coalesce_feed_events(events: list[dict]) -> list[dict]:
    """Merge streaming assistant token events into readable blocks."""
    out: list[dict] = []
    assistant_buf: list[str] = []
    assistant_ts: str | None = None

    def flush_assistant() -> None:
        nonlocal assistant_buf, assistant_ts
        if assistant_buf:
            text = "".join(assistant_buf).strip()
            if text:
                out.append(
                    {"type": "assistant", "text": text, "timestamp": assistant_ts}
                )
            assistant_buf = []
            assistant_ts = None

    for e in events:
        if e.get("type") == "assistant":
            if not assistant_buf:
                assistant_ts = e.get("timestamp")
            assistant_buf.append(e.get("text") or "")
        elif e.get("type") == "rca":
            flush_assistant()
        else:
            flush_assistant()
            out.append(e)
    flush_assistant()
    return out


def build_incident_timeline(
    record: dict, argocd: dict | None, rca: dict | None
) -> list[dict]:
    """Unified chronological timeline from alert, rollout, ArgoCD, and RCA."""
    rows: list[dict] = []

    def add(ts: str | None, kind: str, label: str, detail: str = "") -> None:
        if not ts:
            return
        rows.append(
            {
                "timestamp": ts,
                "kind": kind,
                "label": label,
                "detail": detail,
            }
        )

    add(record.get("created_at"), "investigation", "Investigation opened")

    brief = record.get("brief") or {}
    alert = brief.get("alert") or {}
    rollout = brief.get("rollout") or {}
    add(alert.get("fired_at"), "alert", f"Alert fired — {alert.get('alertname', '')}")
    add(rollout.get("rollout_at"), "rollout", "Kubernetes rollout detected", record["service"])

    argo = argocd or brief.get("argocd")
    if argo:
        add(
            argo.get("last_sync_started"),
            "argocd",
            f"ArgoCD sync started — {argo.get('application', record['service'])}",
            argo.get("last_sync_phase") or "",
        )
        add(
            argo.get("last_sync_finished"),
            "argocd",
            f"ArgoCD sync {argo.get('last_sync_phase', 'completed')}",
            (argo.get("last_sync_message") or "")[:120],
        )
        for h in argo.get("history") or []:
            add(
                h.get("deployed_at"),
                "argocd",
                "ArgoCD deployment recorded",
                f"rev {short_rev(h.get('revision'))}",
            )
        for ev in argo.get("events") or []:
            add(
                ev.get("timestamp"),
                "argocd",
                f"ArgoCD — {ev.get('reason', 'event')}",
                ev.get("message", ""),
            )

    for e in coalesce_feed_events(record.get("events") or []):
        ts = e.get("timestamp")
        et = e.get("type")
        if et == "status" and (e.get("text") or "").startswith("http"):
            add(ts, "investigation", "Cursor agent launched", e.get("text", ""))
        elif et == "status":
            status = e.get("status") or e.get("text") or "status"
            add(ts, "investigation", f"Agent — {status}")
        elif et == "error":
            add(ts, "crashloop", "Investigation error", e.get("text", ""))

    if rca:
        for ev in rca.get("timeline") or []:
            add(ev.get("timestamp"), ev.get("kind", "note"), ev.get("label", ""))

    rows.sort(key=lambda r: r.get("timestamp") or "")
    return rows


def render_timeline(rows: list[dict]) -> None:
    if not rows:
        st.caption("No timeline events yet.")
        return
    parts = ['<div class="ballast-timeline">']
    for row in rows:
        kind = row.get("kind", "note")
        color = KIND_COLOR.get(kind, SLATE)
        dot = badge_inline(kind.replace("_", " "), color)
        detail = row.get("detail", "")
        detail_html = (
            f'<div style="color:#64748b;font-size:0.78rem;margin-top:0.15rem">'
            f"{html_lib.escape(detail)}</div>"
            if detail
            else ""
        )
        parts.append(
            f'<div class="ballast-tl-row">{dot}'
            f'<span class="ballast-tl-ts">{fmt_dt(row.get("timestamp"))}</span>'
            f'<div><strong>{html_lib.escape(row.get("label", ""))}</strong></div>'
            f"{detail_html}</div>"
        )
    parts.append("</div>")
    html_panel("".join(parts))


def render_activity_log(events: list[dict]) -> None:
    coalesced = coalesce_feed_events(events)
    if not coalesced:
        st.caption("Waiting for investigator activity…")
        return

    parts: list[str] = []
    for e in coalesced:
        et = e.get("type", "status")
        ts = fmt_dt(e.get("timestamp"))
        color = EVENT_COLOR.get(et, SLATE)

        if et == "tool_call":
            name = e.get("name") or "tool"
            status = e.get("status") or ""
            parts.append(
                f'<div class="ballast-tool-row">{badge_inline(et, color)}'
                f'<span style="font-family:monospace;font-size:0.72rem;color:#94a3b8">{ts}</span>'
                f"<span><strong>{name}</strong> — {status}</span></div>"
            )
            continue

        if et == "thinking":
            text = (e.get("text") or "").strip()
            if not text:
                continue
            parts.append(
                f'<div class="ballast-activity-card" style="border-left:3px solid {INDIGO}">'
                f'<div class="ballast-activity-ts">{ts} · thinking</div>'
                f'<div class="ballast-activity-body" style="color:#64748b;font-style:italic">'
                f"{html_lib.escape(text)}</div>"
                f"</div>"
            )
            continue

        if et == "assistant":
            text = (e.get("text") or "").strip()
            if not text:
                continue
            parts.append(
                f'<div class="ballast-activity-card" style="border-left:3px solid {TEAL}">'
                f'<div class="ballast-activity-ts">{ts} · agent response</div>'
                f'<div class="ballast-activity-body">{html_lib.escape(text)}</div></div>'
            )
            continue

        bits = " · ".join(
            b for b in (e.get("status"), e.get("name"), e.get("text")) if b
        )
        parts.append(
            f'<div class="ballast-activity-card">'
            f'<div class="ballast-activity-ts">{ts}</div>'
            f"{badge_inline(et, color)} &nbsp; {bits or et}</div>"
        )

    if any(e.get("type") == "rca" for e in events):
        parts.append(
            f'<div class="ballast-activity-card" style="border-left:3px solid {GREEN}">'
            f"{badge_inline('rca', GREEN)} &nbsp; RCA returned and validated against contract</div>"
        )

    html_panel("".join(parts))


def render_argocd_panel(argo: dict | None, service: str) -> None:
    if not argo:
        st.caption(f"No ArgoCD data for `{service}` — is the cluster up?")
        return

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Sync", argo.get("sync_status") or "—", f"rev {short_rev(argo.get('revision'))}")
    with c2:
        st.metric("Health", argo.get("health_status") or "—", fmt_dt(argo.get("health_transition")))
    with c3:
        st.metric("Last operation", argo.get("last_sync_phase") or "—", fmt_dt(argo.get("last_sync_finished")))
    with c4:
        st.metric("Target ref", argo.get("target_revision") or "—", argo.get("application", service))

    msg = argo.get("last_sync_message")
    if msg:
        html_panel(f'<div class="ballast-argocd-msg">{html_lib.escape(msg)}</div>')

    resources = argo.get("sync_resources") or []
    if resources:
        with st.expander("Sync resource results", expanded=False):
            for res in resources:
                status = res.get("status") or "—"
                color = STATUS_COLOR.get(status, SLATE)
                st.markdown(
                    f"{badge_inline(status, color)} **{res.get('kind')}** `{res.get('name')}`"
                    f" — {res.get('message') or ''}",
                    unsafe_allow_html=True,
                )

    events = argo.get("events") or []
    if events:
        with st.expander("ArgoCD cluster events", expanded=False):
            for ev in events:
                st.markdown(
                    f"`{fmt_dt(ev.get('timestamp'))}` **{ev.get('reason')}** "
                    f"({ev.get('type')}) — {ev.get('message')}",
                )

    history = argo.get("history") or []
    if history:
        with st.expander("Deployment history", expanded=False):
            for h in history:
                id_suffix = f" (id {h['id']})" if h.get("id") is not None else ""
                st.markdown(
                    f"`{fmt_dt(h.get('deployed_at'))}` — rev `{short_rev(h.get('revision'), 12)}`"
                    f"{id_suffix}"
                )


def render_rca_panel(record: dict, rca: dict) -> None:
    score = rca["confidence"]["score"]
    top = st.columns([1, 1, 1])
    with top[0]:
        st.markdown(
            f"Confidence &nbsp; "
            f'<span style="color:{conf_color(score)};font-weight:700">{score:.0%}</span>',
            unsafe_allow_html=True,
        )
        st.progress(score)
    with top[1]:
        act = rca["recommended_action"]["action"]
        st.badge(act.replace("_", " "), color=streamlit_badge_color(act))

    with top[2]:
        st.badge(rca["generated_by"], color="blue")
        st.caption(fmt_dt(record.get("created_at")))

    st.markdown(f"### {rca['summary']}")
    st.caption(rca["confidence"]["rationale"])

    col_a, col_b = st.columns(2)
    with col_a:
        with st.expander("Rollout correlation", expanded=True):
            corr = rca["rollout_correlation"]
            st.write(
                f"Rollout **{fmt_dt(corr['rollout_at'])}** → alert "
                f"**{fmt_dt(corr['alert_fired_at'])}** "
                f"({corr['delta_seconds']:.0f}s later, "
                f"{'correlated' if corr['correlated'] else 'not correlated'})"
            )
        with st.expander("Resource change", expanded=True):
            rc = rca["resource_change"]
            st.code(f"{rc['field']}: {rc['previous']} → {rc['current']}")
            st.caption(rc["note"])
    with col_b:
        with st.expander("Recommended action", expanded=True):
            st.write(rca["recommended_action"]["reasoning"])
            st.code(rca["recommended_action"]["remediation"], language="bash")
        with st.expander("Blast radius", expanded=True):
            chips = " ".join(badge_inline(s, SLATE) for s in rca["blast_radius"]["if_rolled_back"])
            st.markdown(chips or "_none_", unsafe_allow_html=True)
            st.caption(
                f"{rca['blast_radius']['graph_source']} — {rca['blast_radius']['note']}"
            )

    with st.expander("Supporting telemetry", expanded=False):
        for s in rca["supporting_telemetry"]:
            link = f" — [open]({s['deeplink']})" if s.get("deeplink") else ""
            q = f"\n`{s['query']}`" if s.get("query") else ""
            st.markdown(f"- **{s['signal']}**: {s['observation']}{link}{q}")

    with st.expander("Evidence", expanded=False):
        for ev in rca["evidence"]:
            link = f" — [link]({ev['deeplink']})" if ev.get("deeplink") else ""
            st.markdown(
                f"- {badge_inline(ev['source'], SLATE)} {ev['detail']}{link}",
                unsafe_allow_html=True,
            )


# ── Sidebar: investigations ───────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚓ Ballast")
    st.caption("GitOps incident response")

    if st.button("＋ Investigate payments", use_container_width=True, type="primary"):
        res = api_post(
            "/investigations",
            {"alertname": "BallastServiceCrashLooping", "service": "payments"},
        )
        if res:
            st.session_state["selected"] = res["id"]

    auto = st.checkbox("Live refresh", value=True)
    st.divider()

    investigations = api_get("/investigations") or []
    if not investigations:
        st.caption("No investigations yet.")
        st.caption("Run `task break` or click above.")
    else:
        options = {rec["id"]: rec for rec in investigations}
        ids = list(options.keys())
        if "selected" not in st.session_state or st.session_state["selected"] not in ids:
            st.session_state["selected"] = ids[0]

        def _label(iid: str) -> str:
            rec = options[iid]
            disp = "●" if rec["status"] in RUNNING else "○"
            return f"{disp} {rec['service']} · {rec['status']}"

        st.radio(
            "Investigations",
            ids,
            format_func=_label,
            key="selected",
        )

        rec = options[st.session_state["selected"]]
        st.caption(rec["alertname"])
        st.caption(fmt_dt(rec["created_at"]))
        st.caption(f"`{rec['id']}`")

    if st.session_state.get("api_error"):
        st.warning(st.session_state["api_error"])

selected = st.session_state.get("selected")
record = api_get(f"/investigations/{selected}") if selected else None
argocd_live = (
    api_get(f"/argocd/applications/{record['service']}")
    if record
    else None
)
kube_live = (
    api_get(f"/kubernetes/services/{record['service']}")
    if record
    else None
)

# ── Main workspace ──────────────────────────────────────────────────────────

if not record:
    st.info("No investigation selected. Use the sidebar to open one or trigger a new investigation.")
else:
    head_l, head_r = st.columns([5, 1])
    with head_l:
        st.markdown(
            f'<p class="ballast-section-head">{record["alertname"]} · {record["service"]}</p>',
            unsafe_allow_html=True,
        )
        st.caption(f"Opened {fmt_dt(record.get('created_at'))}")
    with head_r:
        st.badge(record["status"], color=streamlit_badge_color(record["status"]))

    brief = record.get("brief") or {}
    rollout = brief.get("rollout") or {}
    crash = (kube_live or {}).get("crash_state") or rollout.get("crash_state") or {}
    rca = record.get("rca")

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Service", record["service"])
    with m2:
        mem = (kube_live or {}).get("memory_limit") or rollout.get("current_memory_limit") or "—"
        st.metric(
            "Memory limit",
            mem,
            f"healthy {rollout.get('healthy_memory_limit', '—')}",
        )
    with m3:
        reason = crash.get("display_state") or crash.get("waiting_reason") or "—"
        ready_note = f"{crash.get('ready_pods', 0)}/{crash.get('pods', 0)} ready"
        st.metric("Pod state", reason, f"{crash.get('restarts', 0)} restarts · {ready_note}")
    with m4:
        argo = argocd_live or brief.get("argocd") or {}
        st.metric("ArgoCD sync", argo.get("sync_status") or "—", argo.get("last_sync_phase") or "—")
    with m5:
        st.metric("Investigator", (rca or {}).get("generated_by") or "pending")

    if brief.get("degraded"):
        st.warning("Triage degraded: " + "; ".join(brief["degraded"]))

    cursor_url = next(
        (
            e.get("text")
            for e in record.get("events", [])
            if (e.get("text") or "").startswith("http")
        ),
        None,
    )
    if cursor_url:
        st.link_button("Watch this run in Cursor →", cursor_url)

    if record["status"] == "failed" and record.get("error"):
        st.error(record["error"])

    tab_timeline, tab_gitops, tab_investigation, tab_rca = st.tabs(
        [
            "Timeline",
            "GitOps",
            "Investigation",
            f"Root cause{' ✓' if rca else ''}",
        ]
    )

    timeline_rows = build_incident_timeline(record, argocd_live, rca)

    with tab_timeline:
        pane_title("Chronological incident timeline")
        with st.container(border=True):
            render_timeline(timeline_rows)
        st.caption(f"{len(timeline_rows)} events across alert, rollout, ArgoCD, and investigation.")

    with tab_gitops:
        pane_title("ArgoCD application state")
        render_argocd_panel(argocd_live or brief.get("argocd"), record["service"])

    with tab_investigation:
        pane_title("Agent & engine activity")
        with st.container(height=480, border=True):
            render_activity_log(record.get("events") or [])

    with tab_rca:
        if not rca:
            st.info("Root cause analysis will appear here when the investigation completes.")
            if record["status"] in RUNNING:
                st.caption("Investigation in progress — check the Investigation tab for live activity.")
        else:
            render_rca_panel(record, rca)

if record and record["status"] in RUNNING and selected and auto:
    time.sleep(1.5)
    st.rerun()
