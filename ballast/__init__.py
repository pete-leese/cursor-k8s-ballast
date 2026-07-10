"""k8s-ballast — a Cursor-driven RCA engine for GitOps/Kubernetes incidents.

Given a CrashLoopBackOff alert on the stream fleet, ballast does cheap
deterministic triage (correlate the rollout timestamp with the alert firing
time, read the offending resource change, look up blast radius from
``topology.yaml``), assembles a structured brief, and produces a strict,
validated RCA that recommends rollback vs forward-fix — brief-in / contract-out.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
