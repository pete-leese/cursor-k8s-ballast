"""ballast MCP server — exposes read-only triage + RCA tools a Cursor agent calls.

Run with:
    python -m ballast.mcp_server        # stdio (the Cursor MCP transport)

Add to .cursor/mcp.json:
    "ballast": {
      "command": "python",
      "args": ["-m", "ballast.mcp_server"],
      "cwd": "<repo-root>"
    }

All tools are read-only: they read the declared topology, query Prometheus, read
Kubernetes rollout/crash state, and run the deterministic RCA engine. Nothing
here mutates the cluster.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .cli import _investigation_id
from .engine import analyze, assemble_brief
from .sources import KubernetesSource, PrometheusSource
from .topology import DeclaredTopologySource

_ROOT = Path(__file__).resolve().parent.parent
NAMESPACE = os.environ.get("BALLAST_NAMESPACE", "demo")
PROM_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
REPO = os.environ.get("BALLAST_REPO", "https://github.com/pete-leese/cursor-k8s-ballast")

mcp = FastMCP(
    "ballast",
    instructions=(
        "Read-only tools for investigating Kubernetes CrashLoopBackOff incidents. "
        "Typical flow: get_firing_alerts -> list_services / blast_radius -> "
        "rollout_status -> run_rca. run_rca returns a full validated RCA."
    ),
)

_topology = DeclaredTopologySource(_ROOT / "topology.yaml")


@mcp.tool()
def list_services() -> list[str]:
    """All services in the declared topology (topology.yaml)."""
    return _topology.services()


@mcp.tool()
def blast_radius(service: str) -> dict:
    """Services that (transitively) depend on ``service`` — the rollback blast radius."""
    return {"service": service, "dependents": _topology.dependents(service),
            "graph_source": "declared:topology.yaml"}


@mcp.tool()
def get_firing_alerts() -> list[dict]:
    """Currently firing Prometheus alerts (name, labels, activeAt)."""
    try:
        prom = PrometheusSource(PROM_URL)
        return [
            {"alertname": a.get("labels", {}).get("alertname"),
             "state": a.get("state"), "activeAt": a.get("activeAt"),
             "labels": a.get("labels", {}),
             "annotations": a.get("annotations", {})}
            for a in prom.active_alerts()
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


@mcp.tool()
def query_prometheus(promql: str) -> list[dict]:
    """Run a read-only instant PromQL query and return the raw result vector."""
    try:
        return PrometheusSource(PROM_URL).query(promql)
    except Exception as exc:
        return [{"error": str(exc)}]


@mcp.tool()
def rollout_status(service: str) -> dict:
    """Rollout timestamp, current memory limit and crash state for ``service``."""
    try:
        kube = KubernetesSource(namespace=NAMESPACE)
        dt = kube.rollout_time(service)
        return {
            "service": service,
            "namespace": NAMESPACE,
            "rollout_at": dt.isoformat().replace("+00:00", "Z") if dt else None,
            "memory_limit": kube.memory_limit(service),
            "crash_state": kube.crash_state(service),
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def run_rca(service: str, healthy_memory: str = "128Mi") -> dict:
    """Run the full deterministic RCA for ``service`` and return the validated RCA.

    Correlates the rollout timestamp with the firing alert, characterises the
    resource change, computes blast radius from topology, and recommends
    rollback vs forward-fix.
    """
    try:
        brief = assemble_brief(
            investigation_id=_investigation_id(service),
            service=service,
            namespace=NAMESPACE,
            prometheus=PrometheusSource(PROM_URL),
            kubernetes=KubernetesSource(namespace=NAMESPACE),
            topology=_topology,
            healthy_memory=healthy_memory,
            repo_url=REPO,
        )
        rca = analyze(brief)
        return rca.model_dump(mode="json")
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
