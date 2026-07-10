"""Ballast console — Kubernetes incident response for GitOps fleets.

Sidebar: cluster overview + investigation list.
Main: Verdict · Incident Timeline · GitOps · Agent feed.

Reads from the Ballast API (BALLAST_API_URL).
"""

from __future__ import annotations

import html as html_lib
import math
import os
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
# Cap background reconcile ticks (issue filed, PR not yet visible) at ~60s.
_RECONCILE_TICK_CAP = 20

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
    page_title="Ballast · GitOps incident response",
    layout="wide",
    page_icon=_PAGE_ICON,
)
inject_styles()


def badge(text: str, color: str) -> str:
    return badge_inline(text, color)


def conf_color(score: float) -> str:
    return GREEN if score >= 0.8 else AMBER if score >= 0.5 else RED


def conf_label(score: float) -> str:
    return "High confidence" if score >= 0.8 else (
        "Moderate confidence" if score >= 0.5 else "Low confidence"
    )


def confidence_gauge(score: float) -> str:
    """Return an SVG semicircular gauge for a 0..1 confidence score."""
    score = max(0.0, min(1.0, float(score)))
    color = conf_color(score)
    cx, cy, r = 95, 92, 74
    arc_len = math.pi * r
    offset = arc_len * (1 - score)
    # Needle angle: 180° (left) at 0.0 → 0° (right) at 1.0.
    angle = math.pi * (1 - score)
    nx = cx + (r - 20) * math.cos(angle)
    ny = cy - (r - 20) * math.sin(angle)
    track = f"M {cx - r} {cy} A {r} {r} 0 0 1 {cx + r} {cy}"
    return (
        f'<div class="ballast-gauge">'
        f'<svg viewBox="0 0 190 118" width="190" height="118" '
        f'role="img" aria-label="Confidence {score:.0%}">'
        f'<path d="{track}" fill="none" stroke="#e5e7eb" stroke-width="14" '
        f'stroke-linecap="round"/>'
        f'<path d="{track}" fill="none" stroke="{color}" stroke-width="14" '
        f'stroke-linecap="round" stroke-dasharray="{arc_len:.2f}" '
        f'stroke-dashoffset="{offset:.2f}"/>'
        f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" '
        f'stroke="#0b1220" stroke-width="3" stroke-linecap="round"/>'
        f'<circle cx="{cx}" cy="{cy}" r="5" fill="#0b1220"/>'
        f'<text x="{cx}" y="{cy - 20}" text-anchor="middle" '
        f'class="ballast-gauge-value" fill="{color}">{score:.0%}</text>'
        f"</svg>"
        f'<div class="ballast-gauge-label">{conf_label(score)}</div>'
        f"</div>"
    )


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


def api_delete(path: str, *, timeout: int = 10):
    try:
        r = requests.delete(f"{API}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json() if r.content else {}
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


def _record_signature(rec: dict) -> tuple:
    """Material state of an investigation — a change here warrants a full refresh."""
    return (
        rec.get("status"),
        bool(rec.get("rca")),
        rec.get("remediation_status"),
        bool(rec.get("remediation_pr_url")),
        bool(rec.get("github_issue_url")),
        len(rec.get("events") or []),
    )


def _should_poll(rec: dict) -> bool:
    """Is this investigation still doing something worth watching?"""
    if rec.get("status") in RUNNING:
        return True
    rs = rec.get("remediation_status")
    if rs in ("queued", "creating_issue", "launching_agent") and not rec.get(
        "remediation_pr_url"
    ):
        return True
    if (
        rec.get("github_issue_url")
        and not rec.get("remediation_pr_url")
        and rs in ("complete", "failed")
    ):
        return True
    return False


@st.fragment(run_every=3.0)
def live_refresh_indicator(investigation_id: str) -> None:
    """Poll a running investigation in place (no full-page reload).

    Reruns the whole app only when material state changes; otherwise just
    repaints this small indicator, so the page no longer 'pulses'.
    """
    if not st.session_state.get("auto_refresh", True):
        st.markdown(
            '<div class="ballast-live ballast-live-off">'
            f'{mdi("pause_circle")} live off</div>',
            unsafe_allow_html=True,
        )
        return

    latest = api_get(f"/investigations/{investigation_id}", quiet=True) or {}
    if not latest:
        return

    key = f"_livesig_{investigation_id}"
    tick_key = f"_reconcile_ticks_{investigation_id}"
    new_sig = _record_signature(latest)
    old_sig = st.session_state.get(key)

    # Material change since the last full render → refresh the whole app once.
    if old_sig is not None and new_sig != old_sig:
        # Verdict just landed (rca went absent -> present): notify.
        if not old_sig[1] and new_sig[1]:
            st.session_state["_verdict_toast_id"] = investigation_id
        st.session_state[key] = new_sig
        st.session_state.pop(tick_key, None)
        st.rerun(scope="app")
        return
    st.session_state[key] = new_sig

    active = _should_poll(latest)
    # Cap the issue->PR reconcile so a missing PR doesn't poll forever.
    if active and latest.get("status") not in RUNNING:
        ticks = int(st.session_state.get(tick_key, 0)) + 1
        st.session_state[tick_key] = ticks
        if ticks >= _RECONCILE_TICK_CAP:
            active = False

    if active:
        st.markdown(
            f'<div class="ballast-live">{mdi("sync")} live · refreshing</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="ballast-live ballast-live-idle">'
            f'{mdi("check_circle", filled=True)} up to date</div>',
            unsafe_allow_html=True,
        )


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

    mem_fact = f"<span>Memory</span> <strong>{html_lib.escape(str(mem))}</strong>"
    if healthy_mem not in ("—", None, "") and str(healthy_mem) != str(mem):
        mem_fact += f" <span>(healthy {html_lib.escape(str(healthy_mem))})</span>"
    facts = [
        f"<span>Service</span> <strong>{html_lib.escape(service)}</strong>",
        mem_fact,
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


def render_signal_checklist(
    primary: str,
    signals: dict,
    *,
    alertname: str = "StreamIngestCrashLooping",
) -> None:
    """Checklist of Prometheus / Kubernetes / ArgoCD triggers for the primary service."""
    prom = signals.get("prometheus") or {}
    kube = signals.get("kubernetes") or {}
    argo = signals.get("argocd") or {}

    def code(text: str) -> str:
        return f"<code>{html_lib.escape(str(text))}</code>"

    rows: list[tuple[str, str, str]] = []

    prom_state = prom.get("state")
    if prom.get("error") or prom_state == "error":
        rows.append(("unk", "Prometheus", f"unreachable — {html_lib.escape(str(prom.get('error')))}"))
    elif prom.get("firing") or prom_state == "firing":
        fired = prom.get("fired_at")
        when = f" since {code(fired)}" if fired else ""
        rows.append(("bad", "Prometheus", f"{code(alertname)} firing{when}"))
    elif prom_state == "pending":
        fired = prom.get("fired_at")
        when = f" since {code(fired)}" if fired else ""
        rows.append(
            ("warn", "Prometheus", f"{code(alertname)} pending — in <code>for:</code> window{when}")
        )
    else:
        rows.append(("ok", "Prometheus", f"{code(alertname)} quiet"))

    if kube.get("error"):
        rows.append(("unk", "Kubernetes", f"unreachable — {html_lib.escape(str(kube['error']))}"))
    elif kube.get("incident"):
        reasons = kube.get("reasons") or []
        detail = html_lib.escape("; ".join(reasons) if reasons else "unhealthy pods")
        rows.append(("bad", "Kubernetes", detail))
    else:
        pod = kube.get("pod_state") or "—"
        ready = kube.get("ready_pods")
        total = kube.get("total_pods")
        mem = kube.get("memory_limit")
        bits = [f"pods {code(pod)}"]
        if ready is not None and total is not None:
            bits.append(f"{ready}/{total} ready")
        if mem:
            bits.append(f"mem {code(mem)}")
        rows.append(("ok", "Kubernetes", " · ".join(bits) if bits else "healthy"))

    if argo.get("error"):
        rows.append(("unk", "ArgoCD", f"unreachable — {html_lib.escape(str(argo['error']))}"))
    elif argo.get("note") and not argo.get("sync_status"):
        rows.append(("unk", "ArgoCD", html_lib.escape(str(argo["note"]))))
    elif argo.get("incident"):
        reasons = argo.get("reasons") or []
        sync = argo.get("sync_status") or "—"
        health = argo.get("health_status") or "—"
        detail = html_lib.escape("; ".join(reasons) if reasons else "unhealthy")
        detail += f" ({code(sync)} / {code(health)})"
        rows.append(("bad", "ArgoCD", detail))
    else:
        sync = argo.get("sync_status") or "—"
        health = argo.get("health_status") or "—"
        rows.append(("ok", "ArgoCD", f"sync {code(sync)} · health {code(health)}"))

    icon = {
        "ok": mdi("check_circle", filled=True),
        "bad": mdi("cancel", filled=True),
        "warn": mdi("schedule", filled=True),
        "unk": mdi("help", filled=True),
    }
    body = []
    for state, name, detail in rows:
        body.append(
            f'<div class="ballast-signal-row ballast-signal-{state}">'
            f"{icon[state]}"
            f'<span class="ballast-signal-name">{html_lib.escape(name)}</span>'
            f'<span class="ballast-signal-detail">{detail}</span>'
            f"</div>"
        )

    st.markdown(
        f'<div class="ballast-signals">'
        f'<div class="ballast-signals-head">'
        f"<span>Signal checks</span>"
        f'<span class="ballast-signals-svc">{html_lib.escape(primary)}</span>'
        f"</div>"
        f"{''.join(body)}"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_cluster_overview(overview: dict) -> None:
    primary = overview.get("primary_service", "ingest")
    argo = overview.get("argocd") or {}
    pf = overview.get("preflight") or {}
    healthy = overview.get("healthy", False)
    ballast_firing = overview.get("ballast_alert_firing", False)
    incident = overview.get("incident_detected") or pf.get("incident_detected", False)
    signals = overview.get("signals") or pf.get("signals") or {}
    alertname = pf.get("alertname") or "StreamIngestCrashLooping"

    if healthy:
        st.markdown(
            f'<div class="ballast-healthy">'
            f'{mdi("check_circle", filled=True)} Fleet healthy — no active incidents'
            f"</div>",
            unsafe_allow_html=True,
        )

    render_signal_checklist(primary, signals, alertname=alertname)

    if not healthy:
        existing = pf.get("existing_investigation_id")
        if pf.get("investigation_active") and existing:
            st.markdown(
                f'<p class="ballast-signals-note">'
                f'Investigation <code>{html_lib.escape(existing)}</code> is already running — '
                f"open it in the sidebar.</p>",
                unsafe_allow_html=True,
            )
        elif pf.get("already_investigated") and existing:
            st.markdown(
                f'<p class="ballast-signals-note">'
                f'Already investigated as <code>{html_lib.escape(existing)}</code> — '
                f"open it in the sidebar, or click <strong>Investigate</strong> to jump there.</p>",
                unsafe_allow_html=True,
            )
        elif incident and pf.get("ready"):
            st.markdown(
                f'<p class="ballast-signals-note">'
                f"Failing signals on <strong>{html_lib.escape(primary)}</strong> — "
                f"click <strong>Investigate</strong> for RCA and an auto-fix PR.</p>",
                unsafe_allow_html=True,
            )
        elif not incident:
            degraded = [
                s.get("service")
                for s in overview.get("services", [])
                if not s.get("healthy")
            ]
            if degraded:
                st.markdown(
                    f'<p class="ballast-signals-note">'
                    f"Workload attention on <strong>{html_lib.escape(', '.join(degraded))}</strong>, "
                    f"but no CrashLoop / OOM / ArgoCD Degraded / alert trigger yet. "
                    f"Run <code>task break</code> to induce the demo incident.</p>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<p class="ballast-signals-note">'
                    f"No incident triggers. Run <code>task break</code> to induce CrashLoop / OOM.</p>",
                    unsafe_allow_html=True,
                )

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
    if alert.get("observed", True):
        add(alert.get("fired_at"), "alert", f"Alert fired — {alert.get('alertname', '')}")
    elif alert.get("fired_at"):
        add(
            alert.get("fired_at"),
            "note",
            f"Alert not observed yet — {alert.get('alertname', '')}",
            "Investigating from Kubernetes / ArgoCD signals",
        )
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
    action_label = act.replace("_", " ")

    # ── Verdict header: gauge + summary/decision, in one bordered card ──
    with st.container(border=True):
        gcol, scol = st.columns([1, 2.4], vertical_alignment="center")
        with gcol:
            st.markdown(confidence_gauge(score), unsafe_allow_html=True)
        with scol:
            st.markdown(
                f'<div class="ballast-verdict-meta">'
                f'{badge_inline(action_label, ACTION_COLOR.get(act, SLATE))} '
                f'{badge_inline("by " + rca["generated_by"], SLATE)}'
                f'<span class="ballast-verdict-when">{fmt_dt(record.get("created_at"))}</span>'
                f"</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<p class="ballast-verdict-summary">{html_lib.escape(rca["summary"])}</p>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<p class="ballast-verdict-rationale">'
                f'{mdi("insights")} {html_lib.escape(rca["confidence"]["rationale"])}</p>',
                unsafe_allow_html=True,
            )

    # ── Recommended action — the primary job of this view ──
    with st.container(border=True):
        st.markdown(
            f'<p class="ballast-pane-title">{mdi("bolt")} Recommended action · '
            f'<strong>{html_lib.escape(action_label)}</strong></p>',
            unsafe_allow_html=True,
        )
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
            existing = detail.get("existing_investigation_id")
            if existing:
                st.session_state.pop("all_good", None)
                st.session_state["selected"] = existing
            elif detail.get("cluster_healthy") and not detail.get("incident_detected") and not detail.get("alert_firing"):
                st.session_state["all_good"] = True
                st.session_state["selected"] = CLUSTER_VIEW
            else:
                st.session_state.pop("all_good", None)
                hint = detail.get("hint") or "; ".join(detail.get("blockers") or [])
                st.warning(hint)
        elif res and res.get("id"):
            st.session_state.pop("all_good", None)
            st.session_state["selected"] = res["id"]

    auto = st.checkbox(
        "Auto-refresh while investigating",
        value=True,
        key="auto_refresh",
        help="Live-refreshes only the running investigation in place — no full-page reload.",
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
    if st.session_state.pop("_reset_selection", False):
        st.session_state["selected"] = CLUSTER_VIEW
    if "selected" not in st.session_state or st.session_state["selected"] not in ids:
        st.session_state["selected"] = CLUSTER_VIEW

    def _label(iid: str) -> str:
        if iid == CLUSTER_VIEW:
            return "Cluster overview"
        rec = options[iid]
        disp = "●" if rec["status"] in RUNNING else "○"
        return f"{disp} {iid} · {rec['service']} · {rec['status']}"

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
            f'<p class="ballast-side-meta-alert">{mdi("confirmation_number")} {iid}</p>'
            f'<div class="ballast-side-meta-row">'
            f"<span>{alert}</span>"
            f"<span>{when}</span>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

    if total_investigations:
        st.divider()
        confirm_clear = st.checkbox(
            "Confirm clear all",
            key="confirm_clear_investigations",
            help="Required before clearing — removes every investigation and its artifacts.",
        )
        if st.button(
            "Clear all investigations",
            use_container_width=True,
            disabled=not confirm_clear,
            type="secondary",
        ):
            res = api_delete("/investigations")
            if res is not None:
                # `selected` is the radio widget key — can't be set after the
                # widget exists. Signal the reset and apply it before the radio
                # is built on the next run.
                st.session_state["_reset_selection"] = True
                st.session_state.pop("confirm_clear_investigations", None)
                st.session_state.pop("all_good", None)
                st.rerun()

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
        st.markdown(
            f'<div class="ballast-healthy">'
            f'{mdi("check_circle", filled=True)} Fleet healthy — no active incidents'
            f"</div>",
            unsafe_allow_html=True,
        )
    render_cluster_overview(overview)
elif not record:
    st.info("Select **Cluster overview** in the sidebar or click **Investigate**.")
else:
    head_l, head_r = st.columns([5, 1])
    with head_l:
        masthead(
            f"{record['id']} · {record['service']}",
            f"{record['alertname']} · opened {fmt_dt(record.get('created_at'))}",
            icon="confirmation_number",
        )
        stage_pills("Investigation", ["Overview", "Investigation"], icons=STAGE_ICONS)

    brief = record.get("brief") or {}
    rollout = brief.get("rollout") or {}
    rca = record.get("rca")

    # Seed the live fragment's baseline BEFORE it runs, so this full render
    # doesn't immediately trigger another refresh.
    st.session_state[f"_livesig_{record['id']}"] = _record_signature(record)

    with head_r:
        st.badge(record["status"], color=streamlit_badge_color(record["status"]))
        live_refresh_indicator(record["id"])

    # Toast once when the Verdict lands (rca transitioned absent -> present).
    if st.session_state.get("_verdict_toast_id") == record["id"] and rca:
        st.toast(f"Verdict ready for {record['id']}", icon=":material/gavel:")
        st.session_state.pop("_verdict_toast_id", None)

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
            ["Verdict", "Incident Timeline", "GitOps", "Agent feed"]
        )
    else:
        tab_timeline, tab_gitops, tab_investigation, tab_rca = st.tabs(
            [
                "Incident Timeline",
                "GitOps",
                "Agent feed",
                "Verdict",
            ]
        )

    timeline_rows = build_incident_timeline(record, argocd_live, rca)

    with tab_timeline:
        pane_title("Incident Timeline", icon="timeline")
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

# Live updates while investigating are handled in place by
# `live_refresh_indicator` (a fragment) — no full-page rerun / pulse here.
# Cluster overview stays static and is refreshed via the manual button.
