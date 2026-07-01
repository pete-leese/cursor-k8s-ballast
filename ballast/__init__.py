"""k8s-ballast — a Cursor-driven RCA engine for GitOps/Kubernetes incidents.

The package mirrors the "brief-in / contract-out" pattern from cursor-causa but
targets a Kubernetes + Helm + ArgoCD environment. Given a CrashLoopBackOff alert
it does cheap deterministic triage (correlate the rollout timestamp with the
alert firing time, read the offending resource change, look up blast radius from
``topology.yaml``), assembles a structured brief, and produces a strict,
validated RCA that recommends rollback vs forward-fix.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
