"""Streamlit-safe styling helpers for the Ballast console."""

from __future__ import annotations

import streamlit as st

# Inject once per session via st.html (works reliably on Streamlit 1.58+).
BALLAST_CSS = """
<style>
  .main .block-container {
    padding-top: 1.25rem;
    padding-bottom: 2rem;
    max-width: 1200px;
  }
  section[data-testid="stSidebar"] > div {
    background-color: #f8fafc;
    border-right: 1px solid #e2e8f0;
  }
  section[data-testid="stSidebar"] h2 {
    font-size: 1.1rem !important;
    font-weight: 700 !important;
    color: #0f172a !important;
  }
  /* Default metrics: quiet secondary facts */
  [data-testid="stMetric"] {
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0.15rem 0;
  }
  [data-testid="stMetricLabel"] {
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
    color: #475569 !important;
  }
  [data-testid="stMetricValue"] {
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    color: #0f172a !important;
  }
  [data-testid="stMetricDelta"] {
    font-size: 0.75rem !important;
    color: #475569 !important;
  }
  .ballast-pane-title {
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0;
    text-transform: none;
    color: #475569;
    margin: 0.25rem 0 0.55rem 0;
  }
  .ballast-section-head {
    font-size: 1.2rem;
    font-weight: 700;
    color: #0f172a;
    margin: 0 0 0.75rem 0;
    padding-bottom: 0.45rem;
    border-bottom: 1px solid #e2e8f0;
    text-wrap: balance;
  }
  .ballast-hero {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem 1.25rem;
    align-items: baseline;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 0.85rem 1rem;
    margin: 0 0 0.85rem 0;
  }
  .ballast-hero-label {
    font-size: 0.75rem;
    font-weight: 600;
    color: #475569;
  }
  .ballast-hero-value {
    font-size: 1.15rem;
    font-weight: 700;
    color: #0f172a;
    margin-right: 0.35rem;
  }
  .ballast-hero-meta {
    font-size: 0.8rem;
    color: #334155;
  }
  .ballast-hero--bad .ballast-hero-value { color: #b91c1c; }
  .ballast-hero--ok .ballast-hero-value { color: #15803d; }
  .ballast-corr {
    font-size: 0.84rem;
    color: #334155;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 0.55rem 0.75rem;
    margin: 0 0 0.85rem 0;
    line-height: 1.45;
  }
  .ballast-corr strong { color: #0f172a; font-weight: 600; }
  .ballast-facts {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 1.25rem;
    font-size: 0.82rem;
    color: #334155;
    margin: 0 0 0.85rem 0;
    padding-bottom: 0.65rem;
    border-bottom: 1px solid #f1f5f9;
  }
  .ballast-facts strong { color: #0f172a; font-weight: 600; }
  .ballast-facts span { color: #475569; }
</style>
"""


# Scoped styles bundled into each st.html() block (iframes do not inherit app CSS).
COMPONENT_CSS = """
  .ballast-timeline { position:relative; margin:0.25rem 0; padding-left:1.4rem; }
  .ballast-timeline::before {
    content:""; position:absolute; left:0.45rem; top:0.4rem; bottom:0.4rem;
    width:2px; background:#e2e8f0;
  }
  .ballast-tl-row {
    position:relative; display:flex; flex-wrap:wrap; gap:0.25rem 0.75rem;
    align-items:baseline; padding:0.5rem 0 0.5rem 0.7rem; font-size:0.84rem;
    color:#334155; line-height:1.45;
  }
  .ballast-tl-row::before {
    content:""; position:absolute; left:-1.05rem; top:0.78rem;
    width:9px; height:9px; border-radius:50%; background:#fff; border:2px solid #64748b;
  }
  .ballast-tl-main { flex:1 1 12rem; min-width:0; }
  .ballast-tl-ts {
    font-family:ui-monospace,Menlo,monospace; font-size:0.72rem;
    color:#475569; white-space:nowrap;
  }
  .ballast-tl-detail {
    flex:1 1 100%; color:#475569; font-size:0.78rem; margin-top:0.1rem;
  }
  .ballast-activity-card {
    background:#fff; border:1px solid #e2e8f0; border-radius:6px;
    padding:0.6rem 0.8rem; margin-bottom:0.5rem; font-size:0.84rem; color:#334155;
  }
  .ballast-activity-card--thinking { background:#f8fafc; }
  .ballast-activity-card--assistant { background:#f0fdfa; border-color:#ccfbf1; }
  .ballast-activity-card--rca { background:#f0fdf4; border-color:#bbf7d0; }
  .ballast-activity-ts {
    font-family:ui-monospace,Menlo,monospace; font-size:0.7rem; color:#475569;
    margin-bottom:0.25rem;
  }
  .ballast-activity-body { white-space:pre-wrap; word-break:break-word; line-height:1.5; }
  .ballast-activity-body--muted { color:#475569; }
  .ballast-tool-row {
    display:flex; gap:0.55rem; align-items:baseline; padding:0.4rem 0;
    border-bottom:1px solid #f1f5f9; font-size:0.82rem; color:#334155;
  }
  .ballast-argocd-msg {
    font-size:0.82rem; color:#334155; background:#f8fafc;
    border:1px solid #e2e8f0; padding:0.55rem 0.7rem;
    border-radius:6px; line-height:1.45;
  }
"""


def html_panel(body: str) -> None:
    st.html(f"<style>{COMPONENT_CSS}</style>{body}")


def inject_styles() -> None:
    st.html(BALLAST_CSS)


def badge_inline(text: str, color: str) -> str:
    """Compact status label — rounded rect, not a pill."""
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f"font-size:0.72rem;font-weight:600;white-space:nowrap;"
        f"background:{color}14;color:{color};border:1px solid {color}33\">"
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


def pane_title(text: str) -> None:
    st.markdown(f'<p class="ballast-pane-title">{text}</p>', unsafe_allow_html=True)
