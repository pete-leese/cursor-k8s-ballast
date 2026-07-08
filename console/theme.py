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
  }
  [data-testid="stMetric"] {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 0.55rem 0.75rem;
  }
  [data-testid="stMetricLabel"] {
    font-size: 0.68rem !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #64748b !important;
  }
  [data-testid="stMetricValue"] {
    font-size: 1rem !important;
    font-weight: 700 !important;
    color: #0f172a !important;
  }
  .ballast-pane-title {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #64748b;
    margin: 0.25rem 0 0.6rem 0;
  }
  .ballast-section-head {
    font-size: 1.15rem;
    font-weight: 700;
    color: #0f172a;
    margin: 0 0 0.85rem 0;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid #e2e8f0;
  }
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
    position:relative; padding:0.5rem 0 0.5rem 0.7rem; font-size:0.84rem;
    color:#334155; line-height:1.45;
  }
  .ballast-tl-row::before {
    content:""; position:absolute; left:-1.05rem; top:0.78rem;
    width:9px; height:9px; border-radius:50%; background:#fff; border:2px solid #94a3b8;
  }
  .ballast-tl-ts {
    float:right; font-family:ui-monospace,Menlo,monospace; font-size:0.72rem;
    color:#94a3b8; margin-left:0.5rem;
  }
  .ballast-activity-card {
    background:#fff; border:1px solid #e2e8f0; border-radius:8px;
    padding:0.6rem 0.8rem; margin-bottom:0.5rem; font-size:0.84rem; color:#334155;
  }
  .ballast-activity-ts {
    font-family:ui-monospace,Menlo,monospace; font-size:0.7rem; color:#94a3b8;
    margin-bottom:0.25rem;
  }
  .ballast-activity-body { white-space:pre-wrap; word-break:break-word; line-height:1.5; }
  .ballast-tool-row {
    display:flex; gap:0.55rem; align-items:baseline; padding:0.4rem 0;
    border-bottom:1px solid #f1f5f9; font-size:0.82rem; color:#334155;
  }
  .ballast-argocd-msg {
    font-size:0.82rem; color:#475569; background:#f8fafc;
    border-left:3px solid #cbd5e1; padding:0.55rem 0.7rem;
    border-radius:0 6px 6px 0; line-height:1.45;
  }
"""


def html_panel(body: str) -> None:
    st.html(f"<style>{COMPONENT_CSS}</style>{body}")


def inject_styles() -> None:
    st.html(BALLAST_CSS)


def badge_inline(text: str, color: str) -> str:
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
        f"font-size:0.7rem;font-weight:700;white-space:nowrap;"
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


def pane_title(text: str) -> None:
    st.markdown(f'<p class="ballast-pane-title">{text}</p>', unsafe_allow_html=True)
