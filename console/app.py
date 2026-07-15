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
# Known-good memory limit — mirrors BALLAST_HEALTHY_MEMORY in ballast/preflight.py.
HEALTHY_MEMORY = os.environ.get("BALLAST_HEALTHY_MEMORY", "128Mi")
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


def disable_streamlit_hotkeys() -> None:
    """Suppress Streamlit's built-in "c" = clear-cache dev shortcut.

    Streamlit binds its dev hotkeys via a ``keydown`` listener on the top-level
    ``document``. This console runs inside the top window, but a component iframe
    can reach the parent document through ``window.parent``. We attach a single
    capturing listener there that swallows a plain (or Ctrl/Cmd-held) "c" before
    Streamlit sees it — while leaving Ctrl/Cmd+C copy and typing in fields alone.
    """
    st.iframe(
        """
        <script>
        (function () {
          try {
            var parent = window.parent;
            if (!parent || parent.__ballastHotkeysDisabled) return;
            parent.__ballastHotkeysDisabled = true;
            parent.document.addEventListener('keydown', function (e) {
              var key = (e.key || '').toLowerCase();
              if (key !== 'c') return;
              var t = e.target;
              if (t && t.closest &&
                  t.closest('input, textarea, [contenteditable], [contenteditable=""], [contenteditable="true"]')) {
                return;
              }
              // Stop Streamlit's clear-cache handler. Do NOT preventDefault when
              // a modifier is held, so Ctrl+C / Cmd+C copy still works.
              e.stopImmediatePropagation();
            }, true);
          } catch (err) {
            /* cross-origin or no parent access — fail silently */
          }
        })();
        </script>
        """,
        height=1,
    )


disable_streamlit_hotkeys()


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


def gh_ref(url: str | None) -> str:
    """Return '#<number>' for a GitHub issue/PR URL, else ''."""
    if not url:
        return ""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return f"#{tail}" if tail.isdigit() else ""


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
    # The "verdict landed" toast is decided in the main render from the
    # _verdict_watching/_verdict_seen flags (which survive baseline reseeding),
    # so here we only trigger the refresh.
    if old_sig is not None and new_sig != old_sig:
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


def verdict_complete_toast(vid: str) -> None:
    """Once-only 'analysis complete' toast with a link to that run's Verdict.

    The link is a relative query-param URL (``?view=<id>``). On load the
    sidebar reads ``st.query_params['view']`` and selects that investigation
    before the radio widget is built; because the Verdict tab is first whenever
    an rca exists, selecting the run lands on the verdict — no tab switch
    needed. ``st.toast`` renders markdown, so the link is clickable.
    """
    st.toast(
        f"Analysis complete — {vid}. [Open verdict →](?view={vid})",
        icon=":material/gavel:",
    )


@st.fragment(run_every=4.0)
def verdict_completion_watcher() -> None:
    """View-independent poll that announces a completed analysis anywhere.

    The in-view toast (main render) only fires while the operator is watching
    that specific investigation. This fragment covers the rest: it runs on
    every view (cluster overview or a different run) and toasts once for any run
    that *appears after the page loaded* and reaches a terminal state — even
    fast/auto-created runs (e.g. the backend alert-watcher) that complete
    between polls and were never caught "running".

    Pre-existing runs never toast: the first tick records a session baseline of
    the ids already present at load (``_toast_baseline_ids``); ids in that set
    are ignored forever, so a page load full of already-complete runs stays
    silent. Deduplicates against the in-view toast through the shared
    ``_verdict_seen_<id>`` flag, so exactly one toast fires per completed run
    regardless of which view is active.

    Kept lightweight and consistent with ``live_refresh_indicator``: one
    investigations-list request per tick (a fragment-local repaint, never a
    full-page rerun), plus a single detail fetch only when a fresh run is first
    observed terminal (to confirm the verdict landed, since the list omits rca).
    """
    if not st.session_state.get("auto_refresh", True):
        return
    records = api_get("/investigations", quiet=True) or []
    # One-time session baseline: everything present on the first tick is
    # considered pre-existing and must never toast (no spam for old runs on
    # load). Captured from this same list call.
    if "_toast_baseline_ids" not in st.session_state:
        st.session_state["_toast_baseline_ids"] = {
            rec.get("id") for rec in records if rec.get("id")
        }
    baseline = st.session_state["_toast_baseline_ids"]
    for rec in records:
        vid = rec.get("id")
        if not vid or vid in baseline or st.session_state.get(f"_verdict_seen_{vid}"):
            continue
        watch_key = f"_verdict_watching_{vid}"
        if rec.get("status") in RUNNING:
            # Keep the in-view path consistent; not required to toast anymore.
            st.session_state[watch_key] = True
        else:
            # A run that appeared AND reached a terminal state after load —
            # toast once whether or not we ever caught it running. Confirm the
            # verdict landed (the list omits rca), then mark seen so we neither
            # re-toast nor re-fetch its detail on later ticks.
            detail = api_get(f"/investigations/{vid}", quiet=True) or {}
            if detail.get("rca"):
                verdict_complete_toast(vid)
            st.session_state[f"_verdict_seen_{vid}"] = True


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


# ── Per-service signal derivation ──────────────────────────────────────────
# Mirror the deterministic incident rules from ballast/preflight.py so each
# service in the overview shows a signal chip ONLY when that signal is firing.

_SIGNAL_CHIP_ICON = {"bad": "cancel", "warn": "schedule"}


def _mem_below_healthy(mem: str | None) -> bool:
    """True when a service's memory limit is below the known-good value."""
    if not mem:
        return False
    try:
        cur = int("".join(ch for ch in str(mem) if ch.isdigit()) or "0")
        good = int("".join(ch for ch in HEALTHY_MEMORY if ch.isdigit()) or "0")
        return bool(cur and good and cur < good)
    except ValueError:
        return False


def _kube_signal_reasons(row: dict) -> list[str]:
    """Kubernetes incident reasons for a service (empty when pods are healthy)."""
    if row.get("healthy", False):
        return []
    crash = row.get("crash_state") or {}
    pod = str(row.get("pod_state") or crash.get("display_state") or "unhealthy")
    pod_l = pod.lower()
    waiting = crash.get("waiting_reason")
    oom = (
        crash.get("last_terminated_reason") == "OOMKilled"
        or crash.get("exit_code") == 137
    )
    restarts = int(row.get("restarts") or crash.get("restarts") or 0)
    ready = row.get("ready_pods")
    total = row.get("total_pods")
    reasons: list[str] = []
    if waiting == "CrashLoopBackOff" or "crashloop" in pod_l:
        reasons.append(f"CrashLoopBackOff · {restarts} restarts")
    if oom or "oom" in pod_l:
        reasons.append("OOMKilled")
    if total == 0:
        reasons.append("no pods (Missing)")
    elif total and (ready or 0) < total:
        reasons.append(f"not ready {ready}/{total}")
    mem = row.get("memory_limit")
    if mem and _mem_below_healthy(mem):
        reasons.append(f"mem {mem} < {HEALTHY_MEMORY}")
    if not reasons:
        reasons.append(pod)
    return reasons


def _argo_signal_reasons(row: dict) -> list[str]:
    """ArgoCD incident reasons for a service (empty when synced + healthy)."""
    sync = row.get("argocd_sync")
    health = row.get("argocd_health")
    reasons: list[str] = []
    if health in ("Degraded", "Missing", "Suspended"):
        reasons.append(f"health {health}")
    if sync == "OutOfSync":
        reasons.append("OutOfSync")
    return reasons


def _prom_signal(svc: str, overview: dict, primary: str) -> tuple[str | None, str]:
    """(state, detail) for a service's Prometheus signal — bad/warn/None.

    The primary carries the authoritative firing/pending state (with the
    ``for:`` window) in ``signals.prometheus``; every service can also be
    matched against the demo/stream ``firing_alerts`` list.
    """
    if svc == primary:
        prom = (overview.get("signals") or {}).get("prometheus") or {}
        state = prom.get("state")
        alertname = prom.get("alertname", "alert")
        if prom.get("firing") or state == "firing":
            fired = prom.get("fired_at")
            detail = f"{alertname} firing" + (f" since {fired}" if fired else "")
            return "bad", detail
        if state == "pending":
            return "warn", f"{alertname} pending — in for: window"
    matched = [
        a for a in (overview.get("firing_alerts") or []) if a.get("service") == svc
    ]
    if matched:
        names = ", ".join(
            sorted({a.get("alertname") for a in matched if a.get("alertname")})
        )
        return "bad", (f"{names} firing" if names else "alert firing")
    return None, ""


def _signal_chip(state: str, source: str, detail: str) -> str:
    icon = mdi(_SIGNAL_CHIP_ICON.get(state, "help"), filled=True)
    title = html_lib.escape(detail or source)
    return (
        f'<span class="ballast-chip ballast-chip--{state}" title="{title}">'
        f"{icon}{html_lib.escape(source)}</span>"
    )


def service_signal_chips(row: dict, overview: dict, primary: str) -> str:
    """Compact chips for signals currently FIRING on a service (empty if quiet)."""
    svc = row.get("service", "?")
    chips: list[str] = []

    prom_state, prom_detail = _prom_signal(svc, overview, primary)
    if prom_state:
        chips.append(_signal_chip(prom_state, "Prometheus", prom_detail))

    kube_reasons = _kube_signal_reasons(row)
    if kube_reasons:
        chips.append(_signal_chip("bad", "Kubernetes", "; ".join(kube_reasons)))

    argo_reasons = _argo_signal_reasons(row)
    if argo_reasons:
        chips.append(_signal_chip("bad", "ArgoCD", "; ".join(argo_reasons)))

    if not chips:
        return ""
    return f'<span class="ballast-svc-signals">{"".join(chips)}</span>'


def render_cluster_overview(overview: dict) -> None:
    primary = overview.get("primary_service", "ingest")
    argo = overview.get("argocd") or {}
    pf = overview.get("preflight") or {}
    healthy = overview.get("healthy", False)
    ballast_firing = overview.get("ballast_alert_firing", False)
    incident = overview.get("incident_detected") or pf.get("incident_detected", False)

    if healthy:
        st.markdown(
            f'<div class="ballast-healthy">'
            f'{mdi("check_circle", filled=True)} All healthy — no active incidents'
            f"</div>",
            unsafe_allow_html=True,
        )

    if not healthy:
        # During an incident, guide the operator to the next action. The
        # per-service rows below carry the firing-signal chips inline, so no
        # standalone checklist is needed here.
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
                f"open it in the sidebar, or click <strong>Open investigation</strong> to jump there.</p>",
                unsafe_allow_html=True,
            )
        elif incident and pf.get("ready"):
            st.markdown(
                f'<div class="ballast-problem">'
                f'{mdi("error", filled=True)} Incident detected on {html_lib.escape(primary)}'
                f"</div>",
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

        # Primary call-to-action, shown ONLY while the cluster is unhealthy
        # (this whole block is gated on `not healthy` — the same source of
        # truth the banner uses). When healthy the button is absent entirely,
        # superseding the old always-present-but-disabled sidebar button.
        # Lives inside the live fragment, so it can't set the `selected` radio
        # key directly; it stashes the target in `_pending_selected` and reruns
        # the whole app, where the sidebar applies it before rebuilding the
        # radio. Behavior/flow is otherwise identical to the old handler.
        #
        # This button re-renders every ~5s (it lives in the `run_every`
        # fragment), so it must never spawn more than one investigation per
        # incident. Two guards make that robust:
        #   1. When preflight already knows of an active/recent run for this
        #      incident, the button becomes an "Open investigation" navigator —
        #      it can only jump to the existing run, never create.
        #   2. Otherwise a one-shot in-flight latch disables the button the
        #      moment it is clicked, so a slow POST can't be double-submitted
        #      before the app reruns and navigates away. (The backend is also
        #      idempotent, so even a stray submit reuses the existing record.)
        existing_id = pf.get("existing_investigation_id")
        has_existing = bool(
            existing_id
            and (pf.get("investigation_active") or pf.get("already_investigated"))
        )
        btn_col, _ = st.columns([1, 2])
        with btn_col:
            if has_existing:
                if st.button(
                    "Open investigation",
                    key="open_existing_investigation",
                    use_container_width=True,
                    type="primary",
                ):
                    st.session_state.pop("all_good", None)
                    st.session_state["_investigate_inflight"] = False
                    st.session_state["_pending_selected"] = existing_id
                    st.rerun(scope="app")
            elif st.button(
                "Investigate",
                key="investigate_main",
                use_container_width=True,
                type="primary",
                disabled=bool(st.session_state.get("_investigate_inflight")),
            ):
                st.session_state["_investigate_inflight"] = True
                res = api_post(
                    "/investigations",
                    {"alertname": "StreamIngestCrashLooping", "service": primary},
                )
                if res and res.get("_conflict"):
                    detail = res["_conflict"]
                    existing = detail.get("existing_investigation_id")
                    if existing:
                        st.session_state.pop("all_good", None)
                        st.session_state["_pending_selected"] = existing
                        st.rerun(scope="app")
                    elif detail.get("cluster_healthy") and not detail.get("incident_detected") and not detail.get("alert_firing"):
                        st.session_state["all_good"] = True
                        st.session_state["_pending_selected"] = CLUSTER_VIEW
                        st.rerun(scope="app")
                    else:
                        st.session_state.pop("all_good", None)
                        st.session_state.pop("_investigate_inflight", None)
                        hint = detail.get("hint") or "; ".join(detail.get("blockers") or [])
                        st.warning(hint)
                elif res and res.get("id"):
                    st.session_state.pop("all_good", None)
                    st.session_state["_pending_selected"] = res["id"]
                    st.rerun(scope="app")
                else:
                    # POST failed (api_post already surfaced the error) — release
                    # the latch so the operator can retry.
                    st.session_state.pop("_investigate_inflight", None)

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

    demo_ns = overview.get("demo_namespace") or overview.get("namespace", "demo")
    st.markdown(
        f'<p class="ballast-section-head">{mdi("hub")} Monitored namespaces</p>'
        f'<span class="ballast-ns-label">'
        f'<span class="ballast-ns-label-caption">namespace</span>'
        f'<code class="ballast-ns-label-value">{html_lib.escape(str(demo_ns))}</code>'
        f"</span>",
        unsafe_allow_html=True,
    )
    svc_rows: list[str] = []
    for row in overview.get("services", []):
        svc = row.get("service", "?")
        ok = row.get("healthy", False)
        color = GREEN if ok else RED
        pod = row.get("pod_state") or "—"
        sync = row.get("argocd_sync") or "—"
        health = row.get("argocd_health") or "—"
        mem = row.get("memory_limit") or "—"
        ready = f"{row.get('ready_pods', 0)}/{row.get('total_pods', 0)}"
        chips = service_signal_chips(row, overview, primary)
        meta = (
            f"pods <code>{html_lib.escape(str(pod))}</code> ({ready}) · "
            f"mem <code>{html_lib.escape(str(mem))}</code> · "
            f"ArgoCD <code>{html_lib.escape(str(sync))}</code>"
            f" / <code>{html_lib.escape(str(health))}</code>"
        )
        svc_rows.append(
            f'<div class="ballast-svc-row">'
            f'{badge_inline("ok" if ok else "degraded", color)}'
            f'<span class="ballast-svc-name">{html_lib.escape(str(svc))}</span>'
            f'<span class="ballast-svc-meta">{meta}</span>'
            f"{chips}"
            f"</div>"
        )
    st.markdown(
        f'<div class="ballast-svc-list">{"".join(svc_rows)}</div>',
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


def _overview_signature(overview: dict) -> tuple:
    """Out-of-fragment identity of the cluster state.

    Only fields the *sidebar* depends on live here — a change means the
    investigation list / Investigate target must update, so the fragment
    escalates to a full-app rerun. Health / signal / alert churn is repainted
    inside the fragment and deliberately excluded so it never pulses the page.
    """
    pf = overview.get("preflight") or {}
    return (
        overview.get("primary_service"),
        overview.get("existing_investigation_id") or pf.get("existing_investigation_id"),
        bool(pf.get("investigation_active")),
    )


@st.fragment(run_every=5.0)
def render_cluster_overview_live() -> None:
    """Poll ``/cluster/overview`` in place and repaint the overview panel.

    Mirrors ``live_refresh_indicator``: the fragment re-runs server-side every
    tick and patches only this subtree over the websocket — no full-page reload
    / pulse. Gated by the ``auto_refresh`` sidebar checkbox (read from session
    state, never re-created here). When paused, it stops fetching and repaints
    the last-known overview with a "paused" indicator. A manual refresh button
    forces an immediate re-fetch even while paused. It only escalates to a full
    ``st.rerun(scope="app")`` when the sidebar-relevant identity changes (a new
    investigation appeared / primary service changed).
    """
    live = bool(st.session_state.get("auto_refresh", True))

    ind_col, btn_col = st.columns([4, 1], vertical_alignment="center")
    with btn_col:
        forced = st.button(
            "Refresh",
            key="overview_refresh_now",
            type="secondary",
            use_container_width=True,
            help="Fetch the cluster overview immediately.",
        )

    if live or forced:
        fresh = api_get("/cluster/overview", quiet=True)
        if fresh:
            st.session_state["_overview_cache"] = fresh

    overview_now = st.session_state.get("_overview_cache") or {}

    with ind_col:
        if live:
            st.markdown(
                f'<div class="ballast-live">{mdi("sync")} live · watching cluster</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="ballast-live ballast-live-off">'
                f'{mdi("pause_circle")} live paused</div>',
                unsafe_allow_html=True,
            )

    # Escalate to a full-app rerun only when out-of-fragment UI (the sidebar)
    # must change. Everything else is repainted in place below — no pulse.
    if live:
        sig = _overview_signature(overview_now)
        old_sig = st.session_state.get("_overview_sig")
        st.session_state["_overview_sig"] = sig
        if old_sig is not None and sig != old_sig:
            st.rerun(scope="app")
            return

    render_cluster_overview(overview_now)


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

    cols = st.columns(2)
    with cols[0]:
        if issue_url:
            st.link_button(
                f"GitHub issue {gh_ref(issue_url)} →".replace("  ", " "),
                issue_url,
                use_container_width=True,
            )
            created = record.get("remediation_issue_created_at")
            st.caption(f"Filed {fmt_dt(created)}" if created else "Filed")
        elif in_flight:
            st.caption("GitHub issue — filing…")
        else:
            st.caption("GitHub issue — pending")
    with cols[1]:
        if pr_url:
            st.link_button(
                f"Forward-fix PR {gh_ref(pr_url)} →".replace("  ", " "),
                pr_url,
                use_container_width=True,
            )
            opened = record.get("remediation_pr_opened_at")
            merged = record.get("remediation_pr_merged_at")
            if merged:
                st.caption(f"Merged {fmt_dt(merged)}")
            elif opened:
                st.caption(f"Opened {fmt_dt(opened)}")
            else:
                st.caption("Opened")
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

@st.dialog("Clear all investigations?")
def confirm_clear_all() -> None:
    st.warning(
        "This permanently removes **all** investigation records and their "
        "artifacts. This cannot be undone.",
        icon=":material/warning:",
    )
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button(
            "Yes, clear all",
            key="clear_all_yes",
            use_container_width=True,
            type="primary",
        ):
            res = api_delete("/investigations")
            if res is not None:
                # `selected` is the radio widget key — can't be set after the
                # widget exists. Signal the reset and apply it before the radio
                # is built on the next run.
                st.session_state["_reset_selection"] = True
                st.session_state.pop("all_good", None)
            # Clear the "keep dialog open" flag on both paths so the top-level
            # guard doesn't immediately re-invoke the dialog after it closes.
            st.session_state.pop("_show_clear_dialog", None)
            st.rerun()
    with col_no:
        if st.button(
            "Cancel",
            key="clear_all_cancel",
            use_container_width=True,
            type="secondary",
        ):
            # Clear the flag first, then a bare rerun dismisses the dialog
            # without re-opening it on the next run.
            st.session_state.pop("_show_clear_dialog", None)
            st.rerun()


with st.sidebar:
    st.markdown(brand_block(), unsafe_allow_html=True)
    st.divider()

    investigations = api_get("/investigations") or []
    total_investigations = len(investigations)
    if total_investigations > SIDEBAR_INVESTIGATION_LIMIT:
        investigations = investigations[:SIDEBAR_INVESTIGATION_LIMIT]
    options: dict[str, dict] = {CLUSTER_VIEW: {"id": CLUSTER_VIEW, "service": "cluster", "status": "overview"}}
    for rec in investigations:
        options[rec["id"]] = rec

    ids = [CLUSTER_VIEW] + [rec["id"] for rec in investigations]
    # Query-param navigation: a toast link (`?view=INC-0017`) jumps to that
    # run's Verdict. Apply the selection BEFORE the radio widget is created —
    # a widget-bound session key can't be mutated afterwards (same constraint
    # as `_reset_selection`) — then clear the param so it doesn't re-fire on
    # later reruns. Unknown/stale ids are ignored but still cleared.
    requested_view = st.query_params.get("view")
    if requested_view is not None:
        if requested_view in ids:
            st.session_state.pop("all_good", None)
            st.session_state["selected"] = requested_view
        st.query_params.clear()
    if st.session_state.pop("_reset_selection", False):
        st.session_state["selected"] = CLUSTER_VIEW
    # Main-page Investigate navigation: the button now lives in the cluster
    # overview (inside a fragment, rendered AFTER this radio), so it can't set
    # the `selected` widget key directly. It stashes the target here and reruns
    # the app; we apply it before the radio is (re)created, same constraint as
    # `_reset_selection` above. Unknown ids fall through to the guard below.
    pending_selected = st.session_state.pop("_pending_selected", None)
    if pending_selected is not None and pending_selected in ids:
        st.session_state["selected"] = pending_selected
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
        if st.button(
            "Clear all investigations",
            use_container_width=True,
            type="secondary",
            help="Removes every investigation and its artifacts.",
        ):
            # Don't open the dialog directly here: a background watcher's
            # app-scoped rerun would re-run the script without re-entering this
            # button branch, so Streamlit would auto-dismiss the dialog. Instead
            # set a flag and let the top-level guard re-open it on every run.
            st.session_state["_show_clear_dialog"] = True
            st.rerun()

    if st.session_state.get("api_error"):
        st.warning(st.session_state["api_error"])

    # Settings gear pinned to the BOTTOM of the sidebar. Rendered last, then
    # pushed down by CSS (`.st-key-ballast-sidebar-settings` gets
    # `margin-top:auto`; see theme.py). st.popover always renders its body
    # (open/closed is client-side CSS), so the `auto_refresh` session key that
    # gates the live-poll fragments stays populated whether the menu is open or
    # not — default True, unchanged.
    with st.container(key="ballast-sidebar-settings"):
        with st.popover("", icon=":material/settings:"):
            st.checkbox(
                "Auto-refresh while investigating",
                value=True,
                key="auto_refresh",
                help="Live-refreshes only the running investigation in place — no full-page reload.",
            )

# Re-open the "Clear all investigations?" dialog on EVERY full script run while
# the flag is set. Because this runs at top level (not inside a fragment), an
# app-scoped rerun triggered by a background watcher re-invokes the dialog and
# it stays open instead of being auto-dismissed. The flag is cleared by both
# buttons inside `confirm_clear_all`, so the dialog can't get stuck reopening.
if st.session_state.get("_show_clear_dialog"):
    confirm_clear_all()

selected = st.session_state.get("selected")
cluster_mode = selected == CLUSTER_VIEW
record = api_get(f"/investigations/{selected}") if selected and not cluster_mode else None
argocd_live = api_get(f"/argocd/applications/{record['service']}", quiet=True) if record else None
kube_live = api_get(f"/kubernetes/services/{record['service']}", quiet=True) if record else None

# View-independent completion watcher — fires the "analysis complete" toast
# even when the operator is on the cluster overview or a different run. Renders
# nothing itself; it only shows toasts (deduped via `_verdict_seen_<id>`).
verdict_completion_watcher()

# ── Main workspace ──────────────────────────────────────────────────────────

STAGE_ICONS = {"Overview": "dns", "Investigation": "troubleshoot"}

if cluster_mode:
    masthead(
        "Cluster overview",
        "Live health across services, ArgoCD, and firing alerts.",
        icon="dns",
    )
    stage_pills("Overview", ["Overview", "Investigation"], icons=STAGE_ICONS)
    # The healthy banner is owned solely by `render_cluster_overview` (emitted
    # once whenever the overview reports healthy). Just clear the transient
    # flag here so it doesn't linger — do NOT emit a second banner, or it would
    # stack on top of the fragment's copy after an Investigate click.
    st.session_state.pop("all_good", None)
    # Release the Investigate in-flight latch on every full overview render: a
    # successful submit navigates to the new run (never back here), so reaching
    # this render means no submit is outstanding — reset so a later, genuinely
    # new incident can be investigated again.
    st.session_state.pop("_investigate_inflight", None)
    # Seed the live fragment's baseline from this full render's fetch so its
    # first tick has data (even while paused) and doesn't immediately escalate
    # to a full-app rerun. The panel itself then live-updates in place.
    st.session_state["_overview_cache"] = overview
    st.session_state["_overview_sig"] = _overview_signature(overview)
    render_cluster_overview_live()
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

    # Toast once when the Verdict lands while the user is watching. Tracked via
    # dedicated session flags rather than inferred from the live-refresh
    # baseline: that baseline is reseeded on every full render (line above), so
    # any unrelated rerun after the RCA lands would clobber the absent->present
    # signal and swallow the toast. `_verdict_watching_<id>` records that we saw
    # this investigation pre-verdict (so a later RCA is a "landed while
    # watching" event); `_verdict_seen_<id>` guarantees the toast fires at most
    # once and never for investigations already complete on first open.
    vid = record["id"]
    seen_key = f"_verdict_seen_{vid}"
    watch_key = f"_verdict_watching_{vid}"
    # Runs already present at page load are in the watcher's session baseline and
    # must never toast (shared with `verdict_completion_watcher`, which also
    # dedups via `_verdict_seen_<id>` so a run toasts at most once across both
    # paths). Baseline may be unset if auto-refresh was never on this session.
    toast_baseline = st.session_state.get("_toast_baseline_ids") or set()
    if not rca:
        st.session_state[watch_key] = True
    elif not st.session_state.get(seen_key) and vid not in toast_baseline:
        if st.session_state.get(watch_key):
            verdict_complete_toast(vid)
        st.session_state[seen_key] = True

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

# Live updates are handled in place by fragments — no full-page rerun / pulse
# here. Investigations use `live_refresh_indicator`; the cluster overview uses
# `render_cluster_overview_live`, which re-fetches and repaints its own panel
# every ~5s (gated by `auto_refresh`) with a manual immediate-refresh override.
