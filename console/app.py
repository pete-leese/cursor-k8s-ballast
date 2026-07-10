"""Ballast console — Kubernetes incident response for GitOps fleets.

Sidebar: cluster overview + investigation list.
Main: Verdict · Signal trail · GitOps · Agent feed.

Reads from the Ballast API (BALLAST_API_URL).
"""

from __future__ import annotations

import os
import time
import html as html_lib
from datetime import datetime

import requests
import streamlit as st

from theme import (
    LOGO_PNG,
    badge_inline,
    brand_block,
    html_panel,
    inject_styles,
    masthead,
    mdi,
    pane_title,
    stage_pills,
    streamlit_badge_color,
)

API = os.environ.get("BALLAST_API_URL", "http://localhost:8000")
RUNNING = {"queued", "triaging", "investigating"}
SIDEBAR_INVESTIGATION_LIMIT = 12

# Palette — ink + teal (streaming ops), not causa-slate / purple SaaS
BLUE, GREEN, RED, AMBER, SLATE, TEAL = (
    "#0f766e",
    "#047857",
    "#be123c",
    "#b45309",
    "#4b5563",
    "#0d9488",
)
ACCENT = "#115e59"
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
    "thinking": ACCENT,
    "tool_call": BLUE,
    "assistant": TEAL,
    "error": RED,
    "rca": GREEN,
}
KIND_COLOR = {
    "alert": RED,
    "rollout": BLUE,
    "chart_bump": ACCENT,
    "crashloop": RED,
    "note": SLATE,
    "argocd": TEAL,
    "investigation": ACCENT,
    "remediation": GREEN,
}

_PAGE_ICON = str(LOGO_PNG) if LOGO_PNG.exists() else "◈"
st.set_page_config(
    page_title="Ballast · K8s incident response",
    layout="wide",
    page_icon=_PAGE_ICON,
)
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
    "Why forward-fix ingest instead of rolling back the pipeline?",
    "How does the rollout ↔ alert correlation prove the chart bump?",
    "Which evidence is strongest for the OOMKill?",
    "What breaks for playback if we roll back ingest?",
]


def render_rca_discuss(investigation_id: str, record: dict) -> None:
    status = api_get(f"/investigations/{investigation_id}/chat/status", quiet=True) or {}
    if not status.get("available"):
        st.caption("Follow-up chat needs a Cursor API key on the Ballast API.")
        return

    messages = record.get("chat_messages") or []
    chat_box = st.container(height=320, border=True)
    with chat_box:
        if not messages:
            st.caption(
                "Ask about blast radius, evidence strength, or remediation trade-offs."
            )
        for msg in messages:
            with st.chat_message(msg.get("role", "assistant")):
                st.markdown(msg.get("content", ""))

    pick = st.selectbox(
        "Suggested questions",
        ["—"] + CHAT_STARTERS,
        key=f"rca_starter_pick_{investigation_id}",
    )
    if pick and pick != "—":
        if st.button("Ask", key=f"rca_starter_go_{investigation_id}"):
            with st.spinner("Thinking…"):
                api_post(
                    f"/investigations/{investigation_id}/chat",
                    {"message": pick},
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
        st.caption(f"[Open remediation agent](https://cursor.com/agents/{agent_id})")


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
    """Hero pod/alert signal + dense secondary facts (not five equal metrics)."""
    rollout = rollout or {}
    crash = (kube or {}).get("crash_state") or rollout.get("crash_state") or {}
    argo = argo or {}

    reason = crash.get("display_state") or crash.get("waiting_reason") or "—"
    restarts = crash.get("restarts", 0)
    ready = f"{crash.get('ready_pods', 0)}/{crash.get('pods', 0)}"
    reason_l = str(reason).lower()
    bad = any(
        tok in reason_l
        for tok in ("crash", "oom", "error", "back-off", "backoff", "pending")
    ) or (crash.get("ready_pods", 1) == 0 and crash.get("pods", 0) > 0)
    if firing_count is not None and firing_count > 0:
        bad = True
    hero_mod = "ballast-hero--bad" if bad else "ballast-hero--ok"

    mem = (kube or {}).get("memory_limit") or rollout.get("current_memory_limit") or "—"
    healthy_mem = rollout.get("healthy_memory_limit") or "—"
    sync = argo.get("sync_status") or "—"
    health = argo.get("health_status") or argo.get("last_sync_phase") or "—"

    st.markdown(
        f'<div class="ballast-hero {hero_mod}">'
        f'<div><div class="ballast-hero-label">{mdi("memory")} Pod state</div>'
        f'<span class="ballast-hero-value">{html_lib.escape(str(reason))}</span>'
        f'<span class="ballast-hero-meta"> · {restarts} restarts · {ready} ready</span></div>'
        f"</div>",
        unsafe_allow_html=True,
    )

    facts = [
        f"<span>Service</span> <strong>{html_lib.escape(service)}</strong>",
        f"<span>Memory</span> <strong>{html_lib.escape(str(mem))}</strong>"
        f" <span>(healthy {html_lib.escape(str(healthy_mem))})</span>",
        f"<span>ArgoCD</span> <strong>{html_lib.escape(str(sync))}</strong>"
        f" / <strong>{html_lib.escape(str(health))}</strong>",
    ]
    if firing_count is not None:
        facts.append(
            f"<span>Firing alerts</span> <strong>{firing_count}</strong>"
            f" <span>(stream alerts)</span>"
        )
    elif investigator:
        facts.append(
            f"<span>Investigator</span> <strong>{html_lib.escape(investigator)}</strong>"
        )
    st.markdown(
        f'<div class="ballast-facts">{" · ".join(facts)}</div>',
        unsafe_allow_html=True,
    )


def render_cluster_overview(overview: dict) -> None:
    primary = overview.get("primary_service", "ingest")
    argo = overview.get("argocd") or {}
    pf = overview.get("preflight") or {}
    healthy = overview.get("healthy", False)
    ballast_firing = overview.get("ballast_alert_firing", False)

    if healthy:
        st.success("Cluster looks good — deployments and ArgoCD are healthy. No firing demo alerts.")
    elif ballast_firing:
        st.warning(
            f"**{pf.get('alertname', 'StreamIngestCrashLooping')}** is firing for **{primary}**. "
            "Click **Investigate** for RCA, evidence, and an auto-fix PR."
        )
    else:
        st.info("Some services need attention. Review the board or click **Investigate**.")

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
        f'<p class="ballast-section-head">{mdi("hub")} Services · namespace '
        f'`{overview.get("demo_namespace") or overview.get("namespace", "demo")}`'
        f' <span style="font-weight:500;color:#6b7280;font-size:0.85rem">'
        f'(Ballast product ns: '
        f'`{overview.get("product_namespace", "ballast")}`)</span></p>',
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
        with st.expander(f"Demo / workload firing alerts ({len(firing)})", expanded=ballast_firing):
            for a in firing:
                st.markdown(
                    f"- **{a.get('alertname', '?')}** · service `{a.get('service', '—')}` "
                    f"· ns `{a.get('namespace', '—')}`"
                )

    infra = overview.get("infra_alerts") or []
    if infra:
        with st.expander(
            f"Other cluster alerts ({len(infra)}) — kind control-plane noise, not the demo",
            expanded=False,
        ):
            st.caption(
                "These come from kube-prometheus-stack's default rules (kind doesn't expose "
                "control-plane metrics; `Watchdog` is an always-firing heartbeat by design). "
                "Not related to the stream-ingest incident."
            )
            for a in infra:
                st.markdown(
                    f"- {a.get('alertname', '?')} · ns `{a.get('namespace', '—')}` "
                    f"· `{a.get('severity', '—')}`"
                )

    tab_gitops, tab_deploy = st.tabs(["GitOps", "Deployments"])
    with tab_gitops:
        pane_title("ArgoCD application state", icon="cloud_sync")
        render_argocd_panel(argo, primary, show_history=False)
    with tab_deploy:
        pane_title("Recent ArgoCD deployments", icon="history")
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
            f'<div class="ballast-tl-detail">{detail_body}</div>' if detail else ""
        )
        parts.append(
            f'<div class="ballast-tl-row">{dot}'
            f'<div class="ballast-tl-main">'
            f"<strong>{html_lib.escape(row.get('label', ''))}</strong>"
            f"{detail_html}</div>"
            f'<span class="ballast-tl-ts">{fmt_dt(row.get("timestamp"))}</span>'
            f"</div>"
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
                f'<span style="font-family:monospace;font-size:0.72rem;color:#475569">{ts}</span>'
                f"<span><strong>{name}</strong> — {status}</span></div>"
            )
            continue

        if et == "thinking":
            text = (e.get("text") or "").strip()
            if not text:
                continue
            parts.append(
                f'<div class="ballast-activity-card ballast-activity-card--thinking">'
                f'<div class="ballast-activity-ts">{ts} · thinking</div>'
                f'<div class="ballast-activity-body ballast-activity-body--muted">'
                f"{html_lib.escape(text)}</div>"
                f"</div>"
            )
            continue

        if et == "assistant":
            text = (e.get("text") or "").strip()
            if not text:
                continue
            parts.append(
                f'<div class="ballast-activity-card ballast-activity-card--assistant">'
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
            f'<div class="ballast-activity-card ballast-activity-card--rca">'
            f"{badge_inline('rca', GREEN)} &nbsp; RCA returned and validated against contract</div>"
        )

    html_panel("".join(parts))


def render_argocd_panel(argo: dict | None, service: str, *, show_history: bool = True) -> None:
    if not argo:
        st.caption(f"No ArgoCD data for `{service}` — is the cluster up?")
        return

    sync = argo.get("sync_status") or "—"
    health = argo.get("health_status") or "—"
    phase = argo.get("last_sync_phase") or "—"
    rev = short_rev(argo.get("revision"))
    target = argo.get("target_revision") or "—"
    app = argo.get("application") or service
    facts = [
        f"<span>Sync</span> <strong>{html_lib.escape(str(sync))}</strong>"
        f" <span>(rev {html_lib.escape(str(rev))})</span>",
        f"<span>Health</span> <strong>{html_lib.escape(str(health))}</strong>",
        f"<span>Last op</span> <strong>{html_lib.escape(str(phase))}</strong>"
        f" <span>{html_lib.escape(fmt_dt(argo.get('last_sync_finished')))}</span>",
        f"<span>Target</span> <strong>{html_lib.escape(str(target))}</strong>"
        f" <span>{html_lib.escape(str(app))}</span>",
    ]
    st.markdown(
        f'<div class="ballast-facts">{" · ".join(facts)}</div>',
        unsafe_allow_html=True,
    )

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
    if show_history and history:
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
                "Issue → Cursor agent → forward-fix PR. Links appear as each step completes."
            )
        else:
            st.caption(
                "Auto-remediation is off. Use the button below to file an issue and open a fix PR."
            )

    if status == "failed" and not pr_url:
        st.error(err or "Remediation failed")
        confirm = st.checkbox(
            "Retry will file another issue and launch a new agent",
            key=f"remediate_retry_confirm_{record['id']}",
        )
        if st.button(
            "Retry issue + fix agent",
            key=f"remediate_{record['id']}",
            disabled=not confirm,
        ):
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
        confirm = st.checkbox(
            "I understand this will file a GitHub issue and launch a fix agent",
            key=f"remediate_confirm_{record['id']}",
        )
        if st.button(
            "File issue + launch fix agent",
            key=f"remediate_start_{record['id']}",
            disabled=not confirm,
        ):
            api_post(f"/investigations/{record['id']}/remediate", timeout=30)
            st.rerun()
    elif err and status == "complete":
        st.caption(err)


def render_rca_panel(record: dict, rca: dict) -> None:
    score = rca["confidence"]["score"]
    act = rca["recommended_action"]["action"]

    top = st.columns([1.2, 1, 1])
    with top[0]:
        st.markdown(
            f"Confidence &nbsp; "
            f'<span style="color:{conf_color(score)};font-weight:700">{score:.0%}</span>',
            unsafe_allow_html=True,
        )
        st.progress(score)
    with top[1]:
        st.badge(act.replace("_", " "), color=streamlit_badge_color(act))
    with top[2]:
        st.badge(rca["generated_by"], color="blue")
        st.caption(fmt_dt(record.get("created_at")))

    st.markdown(f"### {rca['summary']}")
    st.caption(rca["confidence"]["rationale"])

    # Decision first — recommended action is the primary job of this view
    st.markdown("**Recommended action**")
    st.write(rca["recommended_action"]["reasoning"])
    st.code(rca["recommended_action"]["remediation"], language="bash")
    render_autofix_status(record, act)

    corr = rca["rollout_correlation"]
    rc = rca["resource_change"]
    with st.expander("Why this happened", expanded=False):
        st.markdown(
            f"Rollout **{fmt_dt(corr['rollout_at'])}** → alert "
            f"**{fmt_dt(corr['alert_fired_at'])}** "
            f"({corr['delta_seconds']:.0f}s later, "
            f"{'correlated' if corr['correlated'] else 'not correlated'})"
        )
        st.code(f"{rc['field']}: {rc['previous']} → {rc['current']}")
        st.caption(rc["note"])

    with st.expander("Blast radius", expanded=False):
        chips = " ".join(
            badge_inline(s, SLATE) for s in rca["blast_radius"]["if_rolled_back"]
        )
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
    with st.expander("Evidence screenshots", expanded=False):
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
                st.caption("_No capture yet — re-run after screenshots are enabled._")
        with shot_cols[1]:
            st.caption("ArgoCD")
            if artifacts["argocd"]:
                render_screenshot_image(
                    record["id"],
                    "argocd.png",
                    caption="ArgoCD application",
                )
            else:
                st.caption("_No capture yet — needs ArgoCD on `:8080`._")
        with shot_cols[2]:
            st.caption("Grafana")
            if artifacts["grafana"]:
                render_screenshot_image(
                    record["id"],
                    "grafana.png",
                    caption="Grafana dashboard",
                )
            else:
                st.caption("_No capture yet — needs Grafana on `:3000`._")

        st.divider()
        for ev in rca["evidence"]:
            link = f" — [link]({ev['deeplink']})" if ev.get("deeplink") else ""
            st.markdown(
                f"- {badge_inline(ev['source'], SLATE)} {ev['detail']}{link}",
                unsafe_allow_html=True,
            )

    with st.expander("Discuss this incident", expanded=False):
        render_rca_discuss(record["id"], record)


# ── Sidebar: investigations ───────────────────────────────────────────────

CLUSTER_VIEW = "__cluster__"
overview = api_get("/cluster/overview") or {}
primary_service = overview.get("primary_service", "ingest")

with st.sidebar:
    st.markdown(brand_block(), unsafe_allow_html=True)

    if st.button("Investigate", use_container_width=True, type="primary"):
        res = api_post(
            "/investigations",
            {"alertname": "StreamIngestCrashLooping", "service": primary_service},
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

    auto = st.checkbox(
        "Auto-refresh while investigating",
        value=True,
        help="Polls only while an investigation or autofix is in progress — not on cluster overview.",
    )
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
            return "Cluster overview"
        rec = options[iid]
        disp = "●" if rec["status"] in RUNNING else "○"
        return f"{disp} {rec['service']} · {rec['status']}"

    st.radio("Investigations", ids, format_func=_label, key="selected")
    if total_investigations > SIDEBAR_INVESTIGATION_LIMIT:
        st.caption(
            f"Showing latest {SIDEBAR_INVESTIGATION_LIMIT} of {total_investigations} investigations."
        )

    sel = st.session_state["selected"]
    if sel != CLUSTER_VIEW and sel in options:
        rec = options[sel]
        alert = html_lib.escape(rec.get("alertname") or "Investigation")
        when = html_lib.escape(fmt_dt(rec.get("created_at")))
        iid = html_lib.escape(rec["id"])
        st.markdown(
            f'<div class="ballast-side-meta">'
            f'<p class="ballast-side-meta-alert">{mdi("notification_important")} {alert}</p>'
            f'<div class="ballast-side-meta-row">'
            f"<span>{when}</span>"
            f'<span class="ballast-side-meta-id">{iid}</span>'
            f"</div></div>",
            unsafe_allow_html=True,
        )
    elif not investigations:
        st.caption(
            "No investigations yet. When a CrashLoop alert fires, click **Investigate** "
            "to run RCA and open a fix PR."
        )

    if st.session_state.get("api_error"):
        st.warning(st.session_state["api_error"])

selected = st.session_state.get("selected")
cluster_mode = selected == CLUSTER_VIEW
record = api_get(f"/investigations/{selected}") if selected and not cluster_mode else None
argocd_live = api_get(f"/argocd/applications/{record['service']}", quiet=True) if record else None
kube_live = api_get(f"/kubernetes/services/{record['service']}", quiet=True) if record else None

# ── Main workspace ──────────────────────────────────────────────────────────

STAGE_ICONS = {"Overview": "dns", "Investigation": "troubleshoot"}

if cluster_mode:
    masthead(
        "Cluster overview",
        "Live health across services, ArgoCD, and firing alerts.",
        icon="dns",
    )
    stage_pills("Overview", ["Overview", "Investigation"], icons=STAGE_ICONS)
    if st.button("Refresh overview", type="secondary"):
        st.rerun()
    if st.session_state.pop("all_good", False):
        st.success("Cluster looks good — no firing demo alerts and workloads are healthy.")
    render_cluster_overview(overview)
elif not record:
    st.info("Select **Cluster overview** in the sidebar or click **Investigate**.")
else:
    head_l, head_r = st.columns([5, 1])
    with head_l:
        masthead(
            f"{record['alertname']} · {record['service']}",
            f"Opened {fmt_dt(record.get('created_at'))}",
            icon="troubleshoot",
        )
        stage_pills("Investigation", ["Overview", "Investigation"], icons=STAGE_ICONS)
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

    # Persistent correlation strip — bridges Timeline ↔ Root cause
    if rca and rca.get("rollout_correlation"):
        corr = rca["rollout_correlation"]
        rc = rca.get("resource_change") or {}
        delta = corr.get("delta_seconds")
        delta_s = f"{delta:.0f}s later" if isinstance(delta, (int, float)) else "—"
        change = ""
        if rc.get("field"):
            change = (
                f" · <strong>{html_lib.escape(str(rc['field']))}</strong> "
                f"{html_lib.escape(str(rc.get('previous', '—')))} → "
                f"{html_lib.escape(str(rc.get('current', '—')))}"
            )
        st.markdown(
            f'<div class="ballast-corr">'
            f"Rollout <strong>{fmt_dt(corr.get('rollout_at'))}</strong> → "
            f"alert <strong>{fmt_dt(corr.get('alert_fired_at'))}</strong> "
            f"({delta_s}"
            f"{', correlated' if corr.get('correlated') else ''})"
            f"{change}</div>",
            unsafe_allow_html=True,
        )

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

    # Root cause first when RCA exists — one job per view
    if rca:
        tab_rca, tab_timeline, tab_gitops, tab_investigation = st.tabs(
            ["Verdict", "Signal trail", "GitOps", "Agent feed"]
        )
    else:
        tab_timeline, tab_gitops, tab_investigation, tab_rca = st.tabs(
            [
                "Signal trail",
                "GitOps",
                "Agent feed",
                "Verdict",
            ]
        )

    timeline_rows = build_incident_timeline(record, argocd_live, rca)

    with tab_timeline:
        pane_title("Signal trail", icon="timeline")
        with st.container(border=True):
            render_timeline(timeline_rows)
        st.caption(f"{len(timeline_rows)} events")

    with tab_gitops:
        pane_title("ArgoCD application", icon="cloud_sync")
        render_argocd_panel(argocd_live or brief.get("argocd"), record["service"])

    with tab_investigation:
        pane_title("Agent & engine feed", icon="terminal")
        with st.container(height=480, border=True):
            render_activity_log(record.get("events") or [])

    with tab_rca:
        if not rca:
            st.info("Verdict will appear here when triage completes.")
            if record["status"] in RUNNING:
                st.caption("In progress — evidence and remediation follow when RCA is ready.")
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
    if waits < 20:  # ~60s at 3s interval
        st.session_state[wait_key] = waits + 1
        needs_refresh = True
# Cluster overview stays static — full-page rerun there caused constant UI flash.

if needs_refresh:
    time.sleep(3.0)
    st.rerun()
