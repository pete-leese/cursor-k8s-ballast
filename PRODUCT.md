# Product

## Register

product

## Platform

web

## Users

Primary users are both (1) FDEs / solution engineers running a live Cursor + Kubernetes GitOps incident demo for customers, and (2) SREs / platform engineers working the same lab as a realistic investigation. Context is a war-room or demo room: fleet board first, then drill into a stream-ingest CrashLoop / OOM episode with evidence, verdict, and remediation. The job in the first ten seconds is: see whether the streaming pipeline is healthy, spot the failing service, and know the next action (triage, ask Ballast, or ship the autofix).

## Product Purpose

Ballast is a Cursor-driven root-cause console for **GitOps / Kubernetes** incidents on a **media-streaming fleet** (ingest → transcode → playback). It correlates rollout timing with alerts, shows blast radius and evidence (Prometheus, ArgoCD, Grafana), recommends rollback vs forward-fix, and can open an autofix PR. Success is trust under pressure: the UI disappears into the investigation so a demo or triage session feels like a serious fleet console—clear, dense, and credible—while still reading well on a projected screen.

This is intentionally a different story from app-code / fintech latency demos: the regression is a Helm values bump, the signal is CrashLoopBackOff / OOMKill, and the control plane is ArgoCD.

## Brand Personality

Technical · Quiet · Credible

Voice is precise and understated. Prefer signal over chrome. Status and evidence speak louder than marketing copy. Urgency comes from the data (firing alerts, CrashLoop, OutOfSync), not from decorative drama.

## Anti-references

- Generic purple SaaS dashboards and “AI platform” marketing energy inside the console
- Neon cyber-ops / sci-fi monitoring skins
- Hero-metric marketing layouts, identical icon-card grids, and decorative glassmorphism
- Fintech “payments / checkout” demo tropes and lookalike Streamlit triage consoles from sibling RCA demos

Prefer ink + teal broadcast/ops density — not slate-on-white SaaS clones.

## Design Principles

1. **Signal over chrome** — Every pixel should help triage or demo narrative; decoration that doesn’t carry state is noise.
2. **Trust under pressure** — Familiar ops patterns, consistent status vocabulary, and readable evidence beat clever UI.
3. **Serious first, stage second** — Optimize for a credible fleet console; then ensure hierarchy and contrast hold on a big screen.
4. **One job per view** — Fleet board answers “is the pipeline OK?”; episode answers “what happened and what do we do?”
5. **Practice what you preach** — The console should feel as disciplined as the RCA contract it surfaces.

## Accessibility & Inclusion

Target WCAG AA contrast for body and UI text. Keep visible focus states. Respect `prefers-reduced-motion` (state changes may crossfade or snap; no decorative motion). Do not rely on color alone for sync/health/alert status—pair color with labels or icons.
