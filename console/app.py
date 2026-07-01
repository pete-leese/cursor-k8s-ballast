"""Ballast console — three-pane Kubernetes RCA investigation view.

LEFT: alerts / investigations (select; simulate an alert).
CENTRE: incident timeline + live investigation feed.
RIGHT: validated RCA — correlation, resource change, blast radius, remediation.

Reads everything from the Ballast API (BALLAST_API_URL).
"""

from __future__ import annotations

import os
import time

import requests
import streamlit as st

API = os.environ.get("BALLAST_API_URL", "http://localhost:8000")
RUNNING = {"queued", "triaging", "investigating"}

BLUE, GREEN, RED, AMBER, SLATE, INDIGO = (
    "#2563eb",
    "#16a34a",
    "#dc2626",
    "#d97706",
    "#64748b",
    "#4f46e5",
)
STATUS_COLOR = {
    "complete": GREEN,
    "failed": RED,
    "queued": SLATE,
    "triaging": AMBER,
    "investigating": AMBER,
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
    "assistant": GREEN,
    "error": RED,
    "rca": GREEN,
}
KIND_COLOR = {
    "alert": RED,
    "rollout": BLUE,
    "chart_bump": INDIGO,
    "crashloop": RED,
    "note": SLATE,
}

st.set_page_config(page_title="Ballast", layout="wide", page_icon="⚓")

st.markdown(
    """
<style>
.block-container { padding-top: 2.2rem; padding-bottom: 2rem; max-width: 1500px; }
h1 { font-size: 1.5rem !important; margin-bottom: 0 !important; }
.ballast-sub { color:#64748b; font-size:0.9rem; margin: 0 0 0.6rem 0; }
.pane-title { font-size:0.78rem; font-weight:700; letter-spacing:0.06em;
  text-transform:uppercase; color:#64748b; margin:0 0 0.4rem 0; }
.badge { padding:2px 9px; border-radius:999px; font-size:0.72rem;
  font-weight:700; white-space:nowrap; }
.feedline { font-size:0.83rem; padding:3px 0; border-bottom:1px solid #eef1f6; }
.tl { padding:5px 0 5px 14px; border-left:2px solid #e2e8f0; margin-left:4px; }
</style>
""",
    unsafe_allow_html=True,
)


def badge(text: str, color: str) -> str:
    return f'<span class="badge" style="background:{color}22;color:{color}">{text}</span>'


def conf_color(score: float) -> str:
    return GREEN if score >= 0.8 else AMBER if score >= 0.5 else RED


def api_get(path: str):
    try:
        r = requests.get(f"{API}{path}", timeout=5)
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


st.markdown("# Ballast")
st.markdown(
    '<p class="ballast-sub">Kubernetes / GitOps RCA console · '
    "CrashLoopBackOff from a bad Helm chart bump</p>",
    unsafe_allow_html=True,
)

left, centre, right = st.columns([1.05, 1.7, 1.9], gap="medium")

with left:
    st.markdown('<p class="pane-title">Alerts</p>', unsafe_allow_html=True)
    if st.button("Investigate payments alert", use_container_width=True, type="primary"):
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
        st.caption("No investigations yet. Run task break, wait for the alert, or click above.")

    _current = st.session_state.get("selected")
    for rec in investigations:
        disp = "running" if rec["status"] in RUNNING else rec["status"]
        is_selected = rec["id"] == _current
        with st.container(border=True):
            col_text, col_btn = st.columns([3, 1])
            with col_text:
                st.markdown(
                    f"**{rec['alertname']}** &nbsp; "
                    + badge(disp, STATUS_COLOR.get(rec["status"], SLATE)),
                    unsafe_allow_html=True,
                )
                st.caption(f"{rec['service']} · {rec['created_at'][11:19]}")
            with col_btn:
                btn_type = "primary" if is_selected else "secondary"
                btn_label = "Viewing" if is_selected else "Open"
                if st.button(btn_label, key=rec["id"], use_container_width=True, type=btn_type):
                    st.session_state["selected"] = rec["id"]

    if st.session_state.get("api_error"):
        st.caption(f"API: {st.session_state['api_error']}")

selected = st.session_state.get("selected")
record = api_get(f"/investigations/{selected}") if selected else None

with centre:
    st.markdown('<p class="pane-title">Incident</p>', unsafe_allow_html=True)
    if not record:
        st.info("Select an investigation on the left, or start one.")
    else:
        st.markdown(
            f"### {record['alertname']} &nbsp; "
            + badge(record["status"], STATUS_COLOR.get(record["status"], SLATE)),
            unsafe_allow_html=True,
        )
        brief = record.get("brief")
        if brief:
            rollout = brief.get("rollout", {})
            if rollout.get("rollout_at"):
                st.caption(
                    f"rollout {rollout['rollout_at'][11:19]} · "
                    f"limit {rollout.get('current_memory_limit', '?')} · "
                    f"service {record['service']}"
                )
            if brief.get("degraded"):
                st.warning("Triage degraded: " + "; ".join(brief["degraded"]))

        cursor_url = next(
            (
                e["text"]
                for e in record.get("events", [])
                if (e.get("text") or "").startswith("http")
            ),
            None,
        )
        if cursor_url:
            st.link_button("Watch this run in Cursor", cursor_url, use_container_width=True)

        rca = record.get("rca")
        if rca and rca.get("timeline"):
            st.markdown("**Timeline**")
            for ev in rca["timeline"]:
                dot = badge(ev["kind"].replace("_", " "), KIND_COLOR.get(ev["kind"], SLATE))
                label = ev["label"]
                if ev.get("deeplink"):
                    label = f"[{label}]({ev['deeplink']})"
                st.markdown(
                    f'<div class="tl">{dot} &nbsp; {label} '
                    f'<span style="color:#94a3b8">{ev["timestamp"][11:19]}</span></div>',
                    unsafe_allow_html=True,
                )

        st.markdown("**Live investigation feed**")
        feed = st.container(height=300, border=True)
        for e in record.get("events", []):
            if e["type"] == "rca":
                feed.markdown(
                    badge("rca", GREEN)
                    + " &nbsp; RCA returned and validated against the contract",
                    unsafe_allow_html=True,
                )
                continue
            bits = " ".join(
                b for b in (e.get("name"), e.get("status"), e.get("text")) if b
            )
            feed.markdown(
                f'<div class="feedline">{badge(e["type"], EVENT_COLOR.get(e["type"], SLATE))}'
                f" &nbsp; {bits}</div>",
                unsafe_allow_html=True,
            )
        if record["status"] == "failed" and record.get("error"):
            st.error(record["error"])

with right:
    st.markdown('<p class="pane-title">Root cause analysis</p>', unsafe_allow_html=True)
    rca = record.get("rca") if record else None
    if not rca:
        st.info("The RCA appears here once the investigation completes.")
    else:
        score = rca["confidence"]["score"]
        top = st.columns([1, 1])
        with top[0]:
            st.markdown(
                f"Confidence &nbsp; "
                f'<span style="color:{conf_color(score)};font-weight:700">{score:.0%}</span>',
                unsafe_allow_html=True,
            )
            st.progress(score)
        with top[1]:
            act = rca["recommended_action"]["action"]
            st.markdown(
                "Recommended "
                + badge(act.replace("_", " "), ACTION_COLOR.get(act, SLATE)),
                unsafe_allow_html=True,
            )
        st.markdown(f"**{rca['summary']}**")
        st.caption(rca["confidence"]["rationale"])

        with st.expander("Rollout correlation", expanded=True):
            corr = rca["rollout_correlation"]
            st.write(
                f"Rollout **{corr['rollout_at'][11:19]}** → alert "
                f"**{corr['alert_fired_at'][11:19]}** "
                f"({corr['delta_seconds']:.0f}s later, "
                f"{'correlated' if corr['correlated'] else 'not correlated'})"
            )

        with st.expander("Resource change", expanded=True):
            rc = rca["resource_change"]
            st.code(f"{rc['field']}: {rc['previous']} → {rc['current']}")
            st.caption(rc["note"])

        with st.expander("Recommended action", expanded=True):
            st.write(rca["recommended_action"]["reasoning"])
            st.code(rca["recommended_action"]["remediation"], language="bash")

        with st.expander("Blast radius", expanded=True):
            chips = " ".join(badge(s, SLATE) for s in rca["blast_radius"]["if_rolled_back"])
            st.markdown(chips or "_none_", unsafe_allow_html=True)
            st.caption(
                f"{rca['blast_radius']['graph_source']} — {rca['blast_radius']['note']}"
            )

        with st.expander("Supporting telemetry"):
            for s in rca["supporting_telemetry"]:
                link = f" — [open]({s['deeplink']})" if s.get("deeplink") else ""
                q = f"\n`{s['query']}`" if s.get("query") else ""
                st.markdown(f"- **{s['signal']}**: {s['observation']}{link}{q}")

        with st.expander("Evidence"):
            for ev in rca["evidence"]:
                link = f" — [link]({ev['deeplink']})" if ev.get("deeplink") else ""
                st.markdown(
                    f"- {badge(ev['source'], SLATE)} {ev['detail']}{link}",
                    unsafe_allow_html=True,
                )

        st.caption(f"Generated by: {rca['generated_by']}")

if record and record["status"] in RUNNING and selected and auto:
    time.sleep(1.5)
    st.rerun()
