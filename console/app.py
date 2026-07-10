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
SIDEBAR_INVESTIGATION_LIMIT = 12

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
    "remediation": GREEN,
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


def api_get(path: str, *, quiet: bool = False):
    try:
        r = requests.get(f"{API}{path}", timeout=8)
        r.raise_for_status()
        if not quiet:
            st.session_state.pop("api_error", None)
        return r.json()
    except Exception as exc:
        if not quiet:
            st.session_state["api_error"] = str(exc)
        return None


def api_get_artifact(investigation_id: str, name: str) -> bytes | None:
    try:
        r = requests.get(
            f"{API}/investigations/{investigation_id}/artifacts/{name}",
            timeout=15,
        )
        if r.status_code == 200 and r.content[:4] == b"\x89PNG":
            return r.content
    except Exception:
        pass
    return None


def investigation_artifacts(record: dict) -> dict[str, bool]:
    names = set(record.get("artifact_names") or [])
    return {
        "prometheus": "prometheus.png" in names,
        "argocd": "argocd.png" in names,
        "grafana": "grafana.png" in names,
    }


def render_screenshot_image(
    investigation_id: str,
    artifact_name: str,
    *,
    caption: str,
) -> bool:
    png = api_get_artifact(investigation_id, artifact_name)
    if not png:
        return False
    st.image(png, caption=caption, use_container_width=True)
    return True


CHAT_STARTERS = [
    "Why forward-fix instead of a full rollback?",
    "Walk me through the rollout ↔ alert correlation.",
    "Which evidence is strongest and why?",
    "What happens to downstream services if we roll back?",
]


def render_rca_discuss(investigation_id: str, record: dict) -> None:
    st.divider()
    pane_title("Discuss findings")

    status = api_get(f"/investigations/{investigation_id}/chat/status", quiet=True) or {}
    if not status.get("available"):
        st.info(
            "RCA chat uses the **Cursor Cloud Agents API**. Add `CURSOR_API_KEY` to "
            "`.env` and restart the Ballast API."
        )
        return

    messages = record.get("chat_messages") or []
    chat_box = st.container(height=360, border=True)
    with chat_box:
        if not messages:
            st.caption(
                "Ask follow-up questions about the RCA — blast radius, evidence, "
                "remediation trade-offs, or what to check next."
            )
        for msg in messages:
            with st.chat_message(msg.get("role", "assistant")):
                st.markdown(msg.get("content", ""))

    starter_cols = st.columns(len(CHAT_STARTERS))
    for idx, question in enumerate(CHAT_STARTERS):
        if starter_cols[idx].button(
            question,
            key=f"rca_starter_{investigation_id}_{idx}",
            use_container_width=True,
        ):
            with st.spinner("Thinking…"):
                api_post(
                    f"/investigations/{investigation_id}/chat",
                    {"message": question},
                    timeout=200,
                )
            st.rerun()

    if prompt := st.chat_input(
        "Ask about the root cause…",
        key=f"rca_chat_{investigation_id}",
    ):
        with st.spinner("Thinking…"):
            api_post(
                f"/investigations/{investigation_id}/chat",
                {"message": prompt},
                timeout=200,
            )
        st.rerun()

    agent_id = status.get("cursor_agent_id")
    if agent_id:
        st.caption(
            f"Continuing via Cursor Cloud Agent `{agent_id}` · "
            f"[open agent](https://cursor.com/agents/{agent_id})"
        )
    model = status.get("model")
    if model:
        st.caption(f"Grounded in RCA + live cluster context · Cursor · {model}")


def api_post(path: str, body: dict | None = None, *, timeout: int = 10):
    try:
        r = requests.post(f"{API}{path}", json=body or {}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 409:
            try:
                return {"_conflict": exc.response.json().get("detail", {})}
            except Exception:
                return {"_conflict": {"hint": str(exc)}}
        detail = None
        if exc.response is not None:
            try:
                payload = exc.response.json()
                detail = payload.get("detail") or payload
            except Exception:
                detail = (exc.response.text or "")[:400]
        if detail:
            st.error(f"API error: {detail}")
        else:
            st.error(f"API error: {exc}")
        return None
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


def render_service_stat_cards(
    service: str,
    kube: dict | None,
    argo: dict | None,
    *,
    rollout: dict | None = None,
    investigator: str | None = None,
    firing_count: int | None = None,
) -> None:
    rollout = rollout or {}
    crash = (kube or {}).get("crash_state") or rollout.get("crash_state") or {}
    argo = argo or {}

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Service", service)
    with m2:
        mem = (kube or {}).get("memory_limit") or rollout.get("current_memory_limit") or "—"
        st.metric("Memory limit", mem, f"healthy {rollout.get('healthy_memory_limit', '—')}")
    with m3:
        reason = crash.get("display_state") or crash.get("waiting_reason") or "—"
        ready_note = f"{crash.get('ready_pods', 0)}/{crash.get('pods', 0)} ready"
        st.metric("Pod state", reason, f"{crash.get('restarts', 0)} restarts · {ready_note}")
    with m4:
        st.metric(
            "ArgoCD sync",
            argo.get("sync_status") or "—",
            argo.get("health_status") or argo.get("last_sync_phase") or "—",
        )
    with m5:
        if firing_count is not None:
            st.metric("Firing alerts", firing_count, "Ballast-related")
        else:
            st.metric("Investigator", investigator or "pending")


def render_cluster_overview(overview: dict) -> None:
    primary = overview.get("primary_service", "payments")
    argo = overview.get("argocd") or {}
    pf = overview.get("preflight") or {}
    healthy = overview.get("healthy", False)
    ballast_firing = overview.get("ballast_alert_firing", False)

    if healthy:
        st.success("Everything looks good — cluster, deployments, and ArgoCD are healthy. No firing alerts.")
    elif ballast_firing:
        st.warning(
            f"**{pf.get('alertname', 'BallastServiceCrashLooping')}** is firing for **{primary}**. "
            "Click **Investigate problems** for RCA, evidence, and an auto-fix PR."
        )
    else:
        st.info("Some services need attention. Review the grid below or click **Investigate problems**.")

    kube_primary = next(
        (s for s in overview.get("services", []) if s.get("service") == primary),
        None,
    )
    render_service_stat_cards(
        primary,
        kube_primary,
        argo,
        firing_count=overview.get("firing_alert_count", 0),
    )

    st.markdown(
        f'<p class="ballast-section-head">Services · namespace `{overview.get("namespace", "ballast")}`</p>',
        unsafe_allow_html=True,
    )
    for row in overview.get("services", []):
        svc = row.get("service", "?")
        ok = row.get("healthy", False)
        color = GREEN if ok else RED
        pod = row.get("pod_state") or "—"
        sync = row.get("argocd_sync") or "—"
        health = row.get("argocd_health") or "—"
        mem = row.get("memory_limit") or "—"
        ready = f"{row.get('ready_pods', 0)}/{row.get('total_pods', 0)}"
        st.markdown(
            f"{badge_inline('ok' if ok else 'degraded', color)} **{svc}** · pods `{pod}` ({ready}) · "
            f"mem `{mem}` · ArgoCD `{sync}` / `{health}`",
            unsafe_allow_html=True,
        )

    prom_error = overview.get("prometheus_error")
    if prom_error:
        st.caption(f"Prometheus unreachable: {prom_error}")

    firing = overview.get("firing_alerts") or []
    if firing:
        with st.expander(f"Ballast-related firing alerts ({len(firing)})", expanded=ballast_firing):
            for a in firing:
                st.markdown(
                    f"- **{a.get('alertname', '?')}** · service `{a.get('service', '—')}` "
                    f"· ns `{a.get('namespace', '—')}`"
                )

    infra = overview.get("infra_alerts") or []
    if infra:
        with st.expander(
            f"Other cluster alerts ({len(infra)}) — kind control-plane noise, not part of the demo",
            expanded=False,
        ):
            st.caption(
                "These come from kube-prometheus-stack's default rules (kind doesn't expose "
                "control-plane metrics; `Watchdog` is an always-firing heartbeat by design). "
                "Not related to the Ballast incident."
            )
            for a in infra:
                st.markdown(
                    f"- {a.get('alertname', '?')} · ns `{a.get('namespace', '—')}` "
                    f"· `{a.get('severity', '—')}`"
                )

    tab_gitops, tab_deploy = st.tabs(["GitOps", "Deployments"])
    with tab_gitops:
        pane_title("ArgoCD application state")
        render_argocd_panel(argo, primary)
    with tab_deploy:
        pane_title("Recent ArgoCD deployments")
        history = (argo or {}).get("history") or []
        if not history:
            st.caption("No deployment history yet.")
        else:
            for h in history[:8]:
                st.markdown(
                    f"`{fmt_dt(h.get('deployed_at'))}` — rev `{short_rev(h.get('revision'), 12)}`"
                )


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

    add(
        record.get("remediation_issue_created_at"),
        "remediation",
        "Auto-remediation — GitHub issue filed",
        record.get("github_issue_url") or "",
    )
    add(
        record.get("remediation_pr_opened_at"),
        "remediation",
        "Auto-remediation — forward-fix PR opened",
        record.get("remediation_pr_url") or "",
    )
    add(
        record.get("remediation_pr_merged_at"),
        "remediation",
        "Auto-remediation — forward-fix PR merged",
        record.get("remediation_pr_url") or "",
    )

    rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
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
        if detail.startswith("http"):
            detail_body = (
                f'<a href="{html_lib.escape(detail)}" target="_blank">{html_lib.escape(detail)}</a>'
            )
        else:
            detail_body = html_lib.escape(detail)
        detail_html = (
            f'<div style="color:#64748b;font-size:0.78rem;margin-top:0.15rem">'
            f"{detail_body}</div>"
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


def render_autofix_status(record: dict, action: str) -> None:
    """Show GitHub issue + fix PR status under forward-fix recommendation."""
    if action not in ("forward_fix", "rollback"):
        return

    status = record.get("remediation_status")
    issue_url = record.get("github_issue_url")
    pr_url = record.get("remediation_pr_url")
    agent_id = record.get("remediation_agent_id")
    err = record.get("remediation_error")
    auto_enabled = os.environ.get("BALLAST_AUTO_REMEDIATE", "0") == "1"
    in_flight = status in ("queued", "creating_issue", "launching_agent")

    st.divider()
    st.markdown("**Auto-remediation**")

    if not status and record.get("status") == "complete":
        if auto_enabled:
            st.caption(
                "Plan: file a GitHub issue from this RCA → launch a Cursor remediation agent "
                "→ open a forward-fix pull request. Links appear here as each step completes."
            )
        else:
            st.caption(
                "Set `BALLAST_AUTO_REMEDIATE=1` (and `CURSOR_API_KEY`) to auto-file an issue "
                "and open a fix PR, or trigger manually below."
            )

    if status == "failed" and not pr_url:
        st.error(err or "Remediation failed")
        if st.button("Retry issue + fix agent", key=f"remediate_{record['id']}"):
            api_post(f"/investigations/{record['id']}/remediate", timeout=30)
            st.rerun()
        if issue_url:
            st.link_button("GitHub issue →", issue_url, use_container_width=True)
        return

    if in_flight:
        st.caption(f"Status: {status.replace('_', ' ')}…")

    cols = st.columns(2)
    with cols[0]:
        if issue_url:
            st.link_button("GitHub issue filed →", issue_url, use_container_width=True)
            created = record.get("remediation_issue_created_at")
            if created:
                st.caption(f"Filed {fmt_dt(created)}")
        elif in_flight:
            st.caption("GitHub issue — filing…")
        else:
            st.caption("GitHub issue — pending")
    with cols[1]:
        if pr_url:
            st.link_button("Forward-fix PR →", pr_url, use_container_width=True)
            opened = record.get("remediation_pr_opened_at")
            merged = record.get("remediation_pr_merged_at")
            if merged:
                st.caption(f"Merged {fmt_dt(merged)}")
            elif opened:
                st.caption(f"Opened {fmt_dt(opened)}")
        elif in_flight or (status == "complete" and agent_id and not pr_url):
            st.caption("Looking up fix PR on GitHub…")
            if agent_id:
                st.link_button(
                    "Remediation agent →",
                    f"https://cursor.com/agents/{agent_id}",
                    use_container_width=True,
                )
        else:
            st.caption("Fix PR — pending")

    if not issue_url and not status and record.get("status") == "complete":
        if st.button("File issue + launch fix agent", key=f"remediate_start_{record['id']}"):
            api_post(f"/investigations/{record['id']}/remediate", timeout=30)
            st.rerun()
    elif err and status == "complete":
        st.caption(err)


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
            render_autofix_status(record, act)
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

    artifacts = investigation_artifacts(record)
    with st.expander("Evidence", expanded=True):
        shot_cols = st.columns(3)
        with shot_cols[0]:
            st.caption("Prometheus")
            if artifacts["prometheus"]:
                render_screenshot_image(
                    record["id"],
                    "prometheus.png",
                    caption="Prometheus firing alerts",
                )
            else:
                st.caption("_No capture yet — re-run investigation after `task setup:playwright`._")
        with shot_cols[1]:
            st.caption("ArgoCD")
            if artifacts["argocd"]:
                render_screenshot_image(
                    record["id"],
                    "argocd.png",
                    caption="ArgoCD application",
                )
            else:
                st.caption(
                    "_No capture yet — re-run after ArgoCD port-forward "
                    "(`:8080`); live login failures fall back to snapshot._"
                )
        with shot_cols[2]:
            st.caption("Grafana")
            if artifacts["grafana"]:
                render_screenshot_image(
                    record["id"],
                    "grafana.png",
                    caption="Grafana dashboard",
                )
            else:
                st.caption(
                    "_No capture yet — re-run investigation with Grafana on "
                    "`:3000` (and Playwright: `task setup:playwright`)._"
                )

        st.divider()
        for ev in rca["evidence"]:
            link = f" — [link]({ev['deeplink']})" if ev.get("deeplink") else ""
            st.markdown(
                f"- {badge_inline(ev['source'], SLATE)} {ev['detail']}{link}",
                unsafe_allow_html=True,
            )

    render_rca_discuss(record["id"], record)


# ── Sidebar: investigations ───────────────────────────────────────────────

CLUSTER_VIEW = "__cluster__"
overview = api_get("/cluster/overview") or {}
primary_service = overview.get("primary_service", "payments")

with st.sidebar:
    st.markdown("## ⚓ Ballast")
    st.caption("GitOps incident response")

    if st.button("Investigate problems", use_container_width=True, type="primary"):
        res = api_post(
            "/investigations",
            {"alertname": "BallastServiceCrashLooping", "service": primary_service},
        )
        if res and res.get("_conflict"):
            detail = res["_conflict"]
            if detail.get("cluster_healthy") and not detail.get("alert_firing"):
                st.session_state["all_good"] = True
                st.session_state["selected"] = CLUSTER_VIEW
            else:
                st.session_state.pop("all_good", None)
                hint = detail.get("hint") or "; ".join(detail.get("blockers") or [])
                st.warning(hint)
                existing = detail.get("existing_investigation_id")
                if existing:
                    st.session_state["selected"] = existing
        elif res and res.get("id"):
            st.session_state.pop("all_good", None)
            st.session_state["selected"] = res["id"]

    auto = st.checkbox("Live refresh", value=True)
    st.divider()

    investigations = api_get("/investigations") or []
    total_investigations = len(investigations)
    if total_investigations > SIDEBAR_INVESTIGATION_LIMIT:
        investigations = investigations[:SIDEBAR_INVESTIGATION_LIMIT]
    options: dict[str, dict] = {CLUSTER_VIEW: {"id": CLUSTER_VIEW, "service": "cluster", "status": "overview"}}
    for rec in investigations:
        options[rec["id"]] = rec

    ids = [CLUSTER_VIEW] + [rec["id"] for rec in investigations]
    if "selected" not in st.session_state or st.session_state["selected"] not in ids:
        st.session_state["selected"] = CLUSTER_VIEW

    def _label(iid: str) -> str:
        if iid == CLUSTER_VIEW:
            return "◎ Cluster overview"
        rec = options[iid]
        disp = "●" if rec["status"] in RUNNING else "○"
        return f"{disp} {rec['service']} · {rec['status']}"

    st.radio("Views", ids, format_func=_label, key="selected")
    if total_investigations > SIDEBAR_INVESTIGATION_LIMIT:
        st.caption(
            f"Showing latest {SIDEBAR_INVESTIGATION_LIMIT} of {total_investigations} investigations."
        )

    sel = st.session_state["selected"]
    if sel != CLUSTER_VIEW and sel in options:
        rec = options[sel]
        st.caption(rec.get("alertname", ""))
        st.caption(fmt_dt(rec.get("created_at")))
        st.caption(f"`{rec['id']}`")
    elif not investigations:
        st.caption("No investigations yet — use **Investigate problems** when an alert fires.")

    if st.session_state.get("api_error"):
        st.warning(st.session_state["api_error"])

selected = st.session_state.get("selected")
cluster_mode = selected == CLUSTER_VIEW
record = api_get(f"/investigations/{selected}") if selected and not cluster_mode else None
argocd_live = api_get(f"/argocd/applications/{record['service']}", quiet=True) if record else None
kube_live = api_get(f"/kubernetes/services/{record['service']}", quiet=True) if record else None

# ── Main workspace ──────────────────────────────────────────────────────────

if cluster_mode:
    st.markdown('<p class="ballast-section-head">Cluster overview</p>', unsafe_allow_html=True)
    st.caption("Live health across deployments, ArgoCD, and Prometheus alerts.")
    if st.session_state.pop("all_good", False):
        st.success("Everything looks good! No firing alerts and workloads are healthy.")
    render_cluster_overview(overview)
elif not record:
    st.info("Select **Cluster overview** in the sidebar or trigger **Investigate problems**.")
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
    rca = record.get("rca")

    render_service_stat_cards(
        record["service"],
        kube_live,
        argocd_live or brief.get("argocd"),
        rollout=rollout,
        investigator=(rca or {}).get("generated_by") or "pending",
    )

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
                st.caption("Investigation in progress — timeline, evidence, and auto-fix PR will follow.")
                if os.environ.get("BALLAST_AUTO_REMEDIATE", "0") == "1":
                    st.caption(
                        "When RCA recommends forward-fix: GitHub issue → Cursor agent → fix PR "
                        "(links appear under Recommended action)."
                    )
        else:
            render_rca_panel(record, rca)

needs_refresh = False
if record and record["status"] in RUNNING and selected and auto:
    needs_refresh = True
elif record and record.get("remediation_status") in (
    "queued",
    "creating_issue",
    "launching_agent",
) and not record.get("remediation_pr_url") and auto:
    needs_refresh = True
elif (
    record
    and auto
    and record.get("github_issue_url")
    and not record.get("remediation_pr_url")
    and record.get("remediation_status") in ("complete", "failed")
):
    # PR may already exist on GitHub; GET reconciles from the issue timeline.
    # Cap polling so a missing PR doesn't spin forever.
    wait_key = f"pr_reconcile_waits_{record['id']}"
    waits = int(st.session_state.get(wait_key, 0))
    if waits < 40:  # ~60s at 1.5s interval
        st.session_state[wait_key] = waits + 1
        needs_refresh = True
elif cluster_mode and auto:
    needs_refresh = True

if needs_refresh:
    time.sleep(1.5)
    st.rerun()
