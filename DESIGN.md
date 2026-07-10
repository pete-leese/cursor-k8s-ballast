# Design System — Ballast console

Visual system for the Streamlit fleet console (`console/`). Register: **product**. Personality: Technical · Quiet · Credible.

## Color strategy

**Committed teal on ink.** Dark sidebar rail + cool gray canvas. Teal (`#0f766e` / `#2dd4bf`) is the brand accent — not slate-blue SaaS and not purple.

| Role | Value | Use |
|------|-------|-----|
| Ink | `#0b1220` | Dark rail, hero strip, headings |
| Canvas | `#f3f4f6` | Main background |
| Body | `#1f2937` | Primary text on light |
| Muted | `#6b7280` / `#9ca3af` | Meta on light / dark |
| Teal | `#0f766e` | Brand, masthead rule, stage-on, corr accents |
| Teal bright | `#2dd4bf` | Brand mark, healthy hero |
| Rose | `#be123c` / `#fb7185` | Degraded / crash |
| Green | `#047857` | Healthy / complete |
| Amber | `#b45309` | Warning / OutOfSync |

## Typography

- **IBM Plex Sans** (UI) + **IBM Plex Mono** (IDs, hero state, timestamps)
- Masthead ~1.45rem / 700 / tight tracking
- Pane titles teal, sentence case
- Square corners (2–4px) — not pill monoculture

## Layout

- Dark sidebar: brand, **Triage fleet**, episode list
- Main: masthead + stage pills (Board / Episode)
- Hero strip is dark ink with mono pod state
- Correlation strip is mint/teal panel
- Episode tabs: **Verdict · Signal trail · GitOps · Agent feed**

## Components

- Badges: 2px radius rects
- Activity cards: full border + tint; no side-stripes
- Timeline markers: square teal ticks (not round dots)

## Anti-patterns (do not reintroduce)

- Side-stripe borders
- Pill monoculture
- Fintech payments/checkout naming
- Slate-on-white “generic RCA console” clone of sibling demos
- Purple SaaS accents
