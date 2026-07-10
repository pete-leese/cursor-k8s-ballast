"""Ballast console visual system — streaming-fleet ops, not generic SaaS slate."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parent / "assets"
LOGO_PNG = ASSETS / "ballast-icon.png"
LOGO_SVG = ASSETS / "ballast-icon.svg"

# Distinctive identity: ink + teal (broadcast/ops), not purple SaaS or causa-slate.
BALLAST_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
  @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,400..600,0..1,0&display=block');

  .material-symbols-outlined {
    font-family: "Material Symbols Outlined" !important;
    font-weight: normal !important;
    font-style: normal !important;
    font-size: 1.25rem;
    line-height: 1;
    letter-spacing: normal;
    text-transform: none;
    display: inline-block;
    white-space: nowrap;
    word-wrap: normal;
    direction: ltr;
    -webkit-font-smoothing: antialiased;
    font-variation-settings: "FILL" 0, "wght" 500, "GRAD" 0, "opsz" 24;
    vertical-align: middle;
    user-select: none;
  }
  .mdi-fill {
    font-variation-settings: "FILL" 1, "wght" 500, "GRAD" 0, "opsz" 24;
  }

  html, body, [class*="css"] {
    font-family: "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif !important;
  }
  code, pre, .stCode, [data-testid="stCaption"] code {
    font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace !important;
  }

  .main .block-container {
    padding-top: 1rem;
    padding-bottom: 2rem;
    max-width: 1120px;
  }

  /* Dark rail — different silhouette from light-sidebar causa-style consoles */
  section[data-testid="stSidebar"] > div {
    background: linear-gradient(180deg, #0b1220 0%, #111827 100%);
    border-right: 1px solid #1f2937;
    color: #e5e7eb;
  }
  section[data-testid="stSidebar"] h2,
  section[data-testid="stSidebar"] label,
  section[data-testid="stSidebar"] p,
  section[data-testid="stSidebar"] span,
  section[data-testid="stSidebar"] .stMarkdown {
    color: #e5e7eb !important;
  }
  section[data-testid="stSidebar"] [data-testid="stCaption"] {
    color: #9ca3af !important;
  }
  section[data-testid="stSidebar"] hr {
    border-color: #1f2937 !important;
  }
  section[data-testid="stSidebar"] .stRadio label {
    color: #d1d5db !important;
  }

  .ballast-brand-block {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    margin: 0 0 0.95rem 0;
  }
  .ballast-logo-img {
    width: 40px;
    height: 40px;
    border-radius: 8px;
    flex-shrink: 0;
    display: block;
  }
  .ballast-brand {
    font-size: 1.35rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #f9fafb !important;
    margin: 0;
    line-height: 1.15;
  }
  .ballast-brand-sub {
    font-size: 0.72rem;
    color: #9ca3af !important;
    margin: 0.15rem 0 0 0;
    line-height: 1.3;
  }

  .ballast-side-meta {
    margin: 0.75rem 0 0.25rem 0;
    padding: 0.7rem 0.75rem;
    background: #0f172a;
    border: 1px solid #1f2937;
    border-radius: 4px;
  }
  .ballast-side-meta-alert {
    font-size: 0.78rem;
    font-weight: 600;
    color: #f3f4f6;
    line-height: 1.35;
    margin: 0 0 0.35rem 0;
    word-break: break-word;
  }
  .ballast-side-meta-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem 0.65rem;
    font-size: 0.7rem;
    color: #9ca3af;
  }
  .ballast-side-meta-id {
    font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace;
    font-size: 0.66rem;
    color: #6b7280;
  }

  /* Main canvas — cool off-white, not warm cream */
  .stApp {
    background: #f3f4f6;
  }

  /* Hide Streamlit's default "Deploy" button in the top toolbar */
  [data-testid="stAppDeployButton"] { display: none !important; }

  /* Hide Streamlit's "Running…" status widget — its per-tick repaint from the
     live-poll fragments causes a flash; we surface polling via .ballast-live. */
  [data-testid="stStatusWidget"] { display: none !important; }

  /* Kill the poll-tick "flash": Streamlit fades element containers to a low
     "stale" opacity during every rerun; the live-poll fragment triggers this
     each tick. Pin stale elements to full opacity so nothing pulses. Hooks the
     stable data-stale attr / stElementContainer testid, not volatile Emotion
     hashes. */
  [data-stale="true"],
  [data-testid="stElementContainer"][data-stale="true"] {
    opacity: 1 !important;
    transition: none !important;
  }

  .ballast-masthead {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 0.75rem 1rem;
    align-items: flex-end;
    margin: 0 0 1rem 0;
    padding-bottom: 0.75rem;
    border-bottom: 3px solid #0f766e;
  }
  .ballast-masthead h1 {
    font-size: 1.45rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #0b1220;
    margin: 0;
    text-wrap: balance;
    display: flex;
    align-items: center;
    gap: 0.45rem;
  }
  .ballast-masthead h1 .material-symbols-outlined {
    color: #0f766e;
    font-size: 1.55rem;
  }
  .ballast-masthead .sub {
    font-size: 0.8rem;
    color: #4b5563;
    margin-top: 0.2rem;
  }

  .ballast-stage {
    display: inline-flex;
    gap: 0.35rem;
    flex-wrap: wrap;
    margin: 0 0 0.85rem 0;
  }
  .ballast-stage-pill {
    font-size: 0.7rem;
    font-weight: 600;
    padding: 0.28rem 0.55rem;
    border-radius: 2px;
    background: #e5e7eb;
    color: #374151;
    border: 1px solid #d1d5db;
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
  }
  .ballast-stage-pill .material-symbols-outlined {
    font-size: 0.95rem;
  }
  .ballast-stage-pill--on {
    background: #0f766e;
    border-color: #0f766e;
    color: #ecfdf5;
  }

  .ballast-hero {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem 1.5rem;
    align-items: baseline;
    background: #0b1220;
    color: #e5e7eb;
    border-radius: 2px;
    padding: 1rem 1.1rem;
    margin: 0 0 0.85rem 0;
  }
  .ballast-hero-label {
    font-size: 0.7rem;
    font-weight: 600;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    display: flex;
    align-items: center;
    gap: 0.3rem;
  }
  .ballast-hero-label .material-symbols-outlined {
    font-size: 1rem;
    color: #2dd4bf;
  }
  .ballast-hero-value {
    font-size: 1.35rem;
    font-weight: 700;
    color: #f9fafb;
    margin-right: 0.4rem;
    font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace;
  }
  .ballast-hero-meta {
    font-size: 0.8rem;
    color: #d1d5db;
  }
  .ballast-hero--bad .ballast-hero-value { color: #fb7185; }
  .ballast-hero--ok .ballast-hero-value { color: #2dd4bf; }

  .ballast-corr {
    font-size: 0.84rem;
    color: #1f2937;
    background: #ecfdf5;
    border: 1px solid #99f6e4;
    border-radius: 2px;
    padding: 0.6rem 0.8rem;
    margin: 0 0 0.85rem 0;
    line-height: 1.45;
  }
  .ballast-corr strong { color: #0f766e; font-weight: 700; }

  .ballast-facts {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 1.35rem;
    font-size: 0.82rem;
    color: #1f2937;
    margin: 0 0 0.9rem 0;
    padding: 0.55rem 0;
    border-top: 1px solid #e5e7eb;
    border-bottom: 1px solid #e5e7eb;
  }
  .ballast-facts strong { color: #0b1220; font-weight: 600; }
  .ballast-facts span { color: #6b7280; }

  .ballast-section-head {
    font-size: 1.05rem;
    font-weight: 700;
    color: #0b1220;
    margin: 1.1rem 0 0.6rem 0;
    letter-spacing: -0.01em;
    display: flex;
    align-items: baseline;
    gap: 0.45rem;
  }
  .ballast-section-head .material-symbols-outlined {
    color: #0f766e;
    font-size: 1.25rem;
    align-self: center;
  }
  .ballast-section-sub {
    font-weight: 500;
    font-size: 0.82rem;
    color: #6b7280;
    letter-spacing: 0;
  }
  .ballast-section-sub code {
    font-size: 0.92em;
    color: #334155;
  }
  /* Namespace label under the "Monitored namespaces" heading — a subtle
     caption + pill, so the value sits on its own line, not inline in the h. */
  .ballast-ns-label {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    margin: -0.35rem 0 0.75rem 0;
  }
  .ballast-ns-label-caption {
    font-size: 0.72rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #64748b;
  }
  .ballast-ns-label-value {
    font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace;
    font-size: 0.76rem;
    font-weight: 600;
    color: #334155;
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 3px;
    padding: 1px 8px;
  }
  .ballast-pane-title {
    font-size: 0.78rem;
    font-weight: 600;
    color: #0f766e;
    margin: 0.2rem 0 0.55rem 0;
    display: flex;
    align-items: center;
    gap: 0.3rem;
  }
  .ballast-pane-title .material-symbols-outlined {
    font-size: 1.05rem;
  }

  .ballast-healthy {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    font-size: 1.05rem;
    font-weight: 650;
    letter-spacing: -0.01em;
    color: #064e3b;
    background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
    border: 1px solid #6ee7b7;
    border-radius: 4px;
    padding: 0.85rem 1.1rem;
    margin: 0 0 1rem 0;
    box-shadow: 0 1px 0 rgba(16, 185, 129, 0.12);
  }
  .ballast-healthy .material-symbols-outlined {
    color: #10b981;
    font-size: 1.75rem;
    font-variation-settings: "FILL" 1, "wght" 600, "GRAD" 0, "opsz" 24;
    filter: drop-shadow(0 1px 1px rgba(5, 150, 105, 0.35));
  }

  .ballast-signals-note {
    margin: 0.1rem 0 1rem 0;
    font-size: 0.85rem;
    color: #64748b;
  }

  /* Per-service overview rows + inline firing-signal chips */
  .ballast-svc-list {
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    background: #fff;
    margin: 0 0 1rem 0;
    overflow: hidden;
  }
  .ballast-svc-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.45rem 0.7rem;
    padding: 0.65rem 0.9rem;
    border-bottom: 1px solid #f1f5f9;
    font-size: 0.86rem;
    line-height: 1.4;
    color: #1f2937;
  }
  .ballast-svc-row:last-child { border-bottom: none; }
  /* Status badge — fixed slot so service names line up row-to-row */
  .ballast-svc-row > span:first-child {
    min-width: 4.75rem;
    text-align: center;
  }
  .ballast-svc-name {
    min-width: 5.5rem;
    font-weight: 700;
    color: #0b1220;
    font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace;
  }
  .ballast-svc-meta { color: #6b7280; font-size: 0.8rem; }
  .ballast-svc-meta code { font-size: 0.82em; color: #334155; }
  .ballast-svc-signals {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    margin-left: auto;
    padding-left: 0.4rem;
  }
  .ballast-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 2px 7px;
    border-radius: 2px;
    font-size: 0.7rem;
    font-weight: 600;
    white-space: nowrap;
    border: 1px solid;
  }
  .ballast-chip .material-symbols-outlined {
    font-size: 0.9rem;
    font-variation-settings: "FILL" 1, "wght" 600, "GRAD" 0, "opsz" 20;
  }
  .ballast-chip--bad {
    color: #be123c;
    background: rgba(190, 18, 60, 0.08);
    border-color: rgba(190, 18, 60, 0.28);
  }
  .ballast-chip--warn {
    color: #b45309;
    background: rgba(180, 83, 9, 0.08);
    border-color: rgba(180, 83, 9, 0.28);
  }

  .ballast-gauge {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.15rem;
  }
  .ballast-gauge svg { overflow: visible; }
  .ballast-gauge-value {
    font-family: "IBM Plex Sans", ui-sans-serif, sans-serif;
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: -0.02em;
  }
  .ballast-gauge-label {
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: #64748b;
    text-transform: uppercase;
    margin-top: -0.35rem;
  }

  .ballast-verdict-meta {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex-wrap: wrap;
    margin-bottom: 0.5rem;
  }
  .ballast-verdict-when {
    margin-left: auto;
    font-size: 0.78rem;
    color: #64748b;
    font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace;
  }
  .ballast-verdict-summary {
    font-size: 1.12rem;
    font-weight: 650;
    line-height: 1.4;
    letter-spacing: -0.01em;
    color: #0b1220;
    margin: 0 0 0.5rem 0;
  }
  .ballast-verdict-rationale {
    display: flex;
    align-items: flex-start;
    gap: 0.35rem;
    font-size: 0.88rem;
    line-height: 1.45;
    color: #64748b;
    margin: 0;
  }
  .ballast-verdict-rationale .material-symbols-outlined {
    font-size: 1.05rem;
    color: #0d9488;
    margin-top: 0.1rem;
  }

  .ballast-live {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    margin-top: 0.35rem;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: #0f766e;
  }
  .ballast-live .material-symbols-outlined {
    font-size: 0.95rem;
    animation: ballast-spin 1.4s linear infinite;
  }
  .ballast-live-idle { color: #64748b; }
  .ballast-live-idle .material-symbols-outlined {
    color: #10b981;
    animation: none;
  }
  .ballast-live-off { color: #6b7280; }
  .ballast-live-off .material-symbols-outlined { animation: none; }
  @keyframes ballast-spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) {
    .ballast-live .material-symbols-outlined { animation: none; }
  }

  [data-testid="stMetric"] {
    background: transparent;
    border: none;
    padding: 0.1rem 0;
  }
  [data-testid="stCaption"] {
    font-size: 0.75rem !important;
  }
  [data-testid="stMetricLabel"] {
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    color: #4b5563 !important;
  }
  [data-testid="stMetricValue"] {
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    color: #0b1220 !important;
  }

  /* Teal CTAs — avoid default Streamlit blue (common in sibling demos) */
  section[data-testid="stSidebar"] .stButton > button[kind="primary"],
  .stButton > button[kind="primary"] {
    background: #0f766e !important;
    border-color: #0f766e !important;
    color: #ecfdf5 !important;
    border-radius: 2px !important;
    font-weight: 600 !important;
  }
  section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover,
  .stButton > button[kind="primary"]:hover {
    background: #115e59 !important;
    border-color: #115e59 !important;
  }
  section[data-testid="stSidebar"] .stButton > button,
  .stButton > button {
    border-radius: 2px !important;
  }

  /* Settings (gear) trigger pinned to the bottom of the sidebar: compact and
     quiet (muted gear, teal hover accent). Targets the stable stPopover testid
     rather than volatile Emotion hashes. */
  section[data-testid="stSidebar"] [data-testid="stPopoverButton"],
  section[data-testid="stSidebar"] [data-testid="stPopoverButton"]:hover,
  section[data-testid="stSidebar"] [data-testid="stPopoverButton"]:focus,
  section[data-testid="stSidebar"] [data-testid="stPopoverButton"][aria-expanded="true"] {
    border-radius: 2px !important;
    padding: 0.25rem 0.4rem !important;
    min-height: 0 !important;
    color: #0f766e !important;
    background: rgba(15, 118, 110, 0.08) !important;
    border-color: transparent !important;
  }
  section[data-testid="stSidebar"] [data-testid="stPopoverButton"] [data-testid="stIconMaterial"] {
    color: #0f766e !important;
  }

  /* Bottom-pin the settings gear. Streamlit has no native sticky-bottom, so we
     stretch the sidebar content into a full-height flex column, then push the
     gear's layout wrapper down with margin-top:auto. The actual ancestry is
     stSidebarUserContent > div > stVerticalBlock(main) > stLayoutWrapper >
     .st-key-ballast-sidebar-settings, so the auto margin must sit on the
     stLayoutWrapper (the direct flex child of the tall main block), not on the
     settings container (which lives inside a shrink-wrapped 40px wrapper).
     Stable testids / key-class only — no Emotion hashes. */
  section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div
    > [data-testid="stVerticalBlock"] {
    flex: 1 1 auto;
  }
  section[data-testid="stSidebar"] [data-testid="stLayoutWrapper"]:has(
      > .st-key-ballast-sidebar-settings
    ) {
    margin-top: auto !important;
  }

  /* Square-ish tabs, not pill SaaS */
  button[data-baseweb="tab"] {
    border-radius: 2px 2px 0 0 !important;
    font-weight: 600 !important;
  }
  button[data-baseweb="tab"][aria-selected="true"] {
    color: #0f766e !important;
  }
</style>
"""

COMPONENT_CSS = """
  .ballast-timeline { position:relative; margin:0.25rem 0; padding-left:1.35rem; }
  .ballast-timeline::before {
    content:""; position:absolute; left:0.4rem; top:0.35rem; bottom:0.35rem;
    width:2px; background:#99f6e4;
  }
  .ballast-tl-row {
    position:relative; display:flex; flex-wrap:wrap; gap:0.25rem 0.75rem;
    align-items:baseline; padding:0.45rem 0 0.45rem 0.65rem; font-size:0.84rem;
    color:#1f2937; line-height:1.45;
  }
  .ballast-tl-row::before {
    content:""; position:absolute; left:-1.05rem; top:0.72rem;
    width:8px; height:8px; border-radius:1px; background:#0f766e; border:0;
  }
  .ballast-tl-main { flex:1 1 12rem; min-width:0; }
  .ballast-tl-ts {
    font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace; font-size:0.7rem;
    color:#6b7280; white-space:nowrap;
  }
  .ballast-tl-detail {
    flex:1 1 100%; color:#4b5563; font-size:0.78rem; margin-top:0.1rem;
  }
  .ballast-activity-card {
    background:#fff; border:1px solid #e5e7eb; border-radius:2px;
    padding:0.55rem 0.75rem; margin-bottom:0.45rem; font-size:0.84rem; color:#1f2937;
  }
  .ballast-activity-card--thinking { background:#f9fafb; }
  .ballast-activity-card--assistant { background:#f0fdfa; border-color:#99f6e4; }
  .ballast-activity-card--rca { background:#ecfdf5; border-color:#5eead4; }
  .ballast-activity-ts {
    font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace; font-size:0.68rem; color:#6b7280;
    margin-bottom:0.2rem;
  }
  .ballast-activity-body { white-space:pre-wrap; word-break:break-word; line-height:1.5; }
  .ballast-activity-body--muted { color:#4b5563; }
  .ballast-tool-row {
    display:flex; gap:0.55rem; align-items:baseline; padding:0.35rem 0;
    border-bottom:1px solid #f3f4f6; font-size:0.82rem; color:#1f2937;
  }
  .ballast-argocd-msg {
    font-size:0.82rem; color:#1f2937; background:#f9fafb;
    border:1px solid #e5e7eb; padding:0.55rem 0.7rem;
    border-radius:2px; line-height:1.45;
  }
"""


def mdi(name: str, *, filled: bool = False, size: int | None = None, cls: str = "") -> str:
    """Google Material Symbols Outlined icon."""
    classes = ["material-symbols-outlined"]
    if filled:
        classes.append("mdi-fill")
    if cls:
        classes.append(cls)
    style = f' style="font-size:{size}px"' if size else ""
    return f'<span class="{" ".join(classes)}"{style} aria-hidden="true">{name}</span>'


def brand_block(subtitle: str = "GitOps incident response") -> str:
    """Sidebar product mark: logo image + wordmark."""
    if LOGO_SVG.exists():
        svg = LOGO_SVG.read_text(encoding="utf-8")
        svg = svg.replace(
            "<svg ",
            '<svg class="ballast-logo-img" width="40" height="40" ',
            1,
        )
        logo = svg
    elif LOGO_PNG.exists():
        logo = mdi("monitoring", filled=True, size=36)
    else:
        logo = mdi("monitoring", filled=True, size=36)
    return (
        f'<div class="ballast-brand-block">{logo}'
        f'<div><p class="ballast-brand">Ballast</p>'
        f'<p class="ballast-brand-sub">{subtitle}</p></div></div>'
    )


def html_panel(body: str) -> None:
    st.html(f"<style>{COMPONENT_CSS}</style>{body}")


def inject_styles() -> None:
    st.html(BALLAST_CSS)


def badge_inline(text: str, color: str) -> str:
    return (
        f'<span style="display:inline-block;padding:2px 7px;border-radius:2px;'
        f"font-size:0.7rem;font-weight:600;white-space:nowrap;"
        f"background:{color}18;color:{color};border:1px solid {color}40\">"
        f"{text}</span>"
    )


def streamlit_badge_color(status: str) -> str:
    return {
        "complete": "green",
        "failed": "red",
        "queued": "gray",
        "triaging": "orange",
        "investigating": "orange",
        "Synced": "green",
        "OutOfSync": "orange",
        "Healthy": "green",
        "Degraded": "red",
        "Failed": "red",
        "Succeeded": "green",
    }.get(status, "blue")


def pane_title(text: str, icon: str | None = None) -> None:
    lead = f"{mdi(icon)} " if icon else ""
    st.markdown(
        f'<p class="ballast-pane-title">{lead}{text}</p>',
        unsafe_allow_html=True,
    )


def masthead(title: str, subtitle: str = "", icon: str | None = None) -> None:
    lead = f"{mdi(icon)} " if icon else ""
    sub = f'<div class="sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="ballast-masthead"><div><h1>{lead}{title}</h1>{sub}</div></div>',
        unsafe_allow_html=True,
    )


def stage_pills(
    active: str, stages: list[str], icons: dict[str, str] | None = None
) -> None:
    icons = icons or {}
    bits = []
    for s in stages:
        cls = (
            "ballast-stage-pill ballast-stage-pill--on"
            if s == active
            else "ballast-stage-pill"
        )
        ic = mdi(icons[s]) + " " if s in icons else ""
        bits.append(f'<span class="{cls}">{ic}{s}</span>')
    st.markdown(f'<div class="ballast-stage">{"".join(bits)}</div>', unsafe_allow_html=True)
