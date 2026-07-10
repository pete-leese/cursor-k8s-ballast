"""Command-line entrypoint for the ballast RCA engine.

    python -m ballast.cli investigate --service ingest --healthy-memory 128Mi
    python -m ballast.cli blast-radius ingest
    python -m ballast.cli schema > schema/rca.schema.json

``investigate`` runs live triage against Prometheus + the cluster, correlates the
rollout with the alert, and prints a validated RCA (also written to
``--out`` if given). ``--mock`` replays a fixture instead of touching the cluster.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .contract import RCA
from .engine import analyze, assemble_brief
from .investigator import MockInvestigator
from .sources import KubernetesSource, PrometheusSource
from .topology import DeclaredTopologySource

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "https://github.com/pete-leese/cursor-k8s-ballast"


def _investigation_id(service: str) -> str:
    """CLI one-shot id — ticket-shaped, not persisted in the console store."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"INC-CLI-{stamp}-{service}"


def cmd_investigate(args: argparse.Namespace) -> int:
    topology = DeclaredTopologySource(_ROOT / "topology.yaml")

    if args.mock:
        inv = MockInvestigator()
        rca = inv.rca(service=args.service, investigation_id=_investigation_id(args.service))
        print(rca.model_dump_json(indent=2))
        if args.out:
            Path(args.out).write_text(rca.model_dump_json(indent=2) + "\n")
        return 0

    prom = PrometheusSource(args.prometheus_url) if args.prometheus_url else None
    kube = KubernetesSource(namespace=args.namespace) if not args.no_cluster else None

    brief = assemble_brief(
        investigation_id=_investigation_id(args.service),
        service=args.service,
        namespace=args.namespace,
        prometheus=prom,
        kubernetes=kube,
        topology=topology,
        healthy_memory=args.healthy_memory,
        repo_url=args.repo_url,
        alertname=args.alertname,
    )

    # Demo aids: when there is no cluster to read (e.g. a host that cannot host
    # nested Kubernetes), supply the rollout/crash facts a live cluster would
    # otherwise provide, so the engine can still correlate against a real
    # Prometheus alert. These are explicit overrides, never silent defaults.
    if args.rollout_at:
        brief.rollout.rollout_at = args.rollout_at
    if args.current_memory:
        brief.rollout.current_memory_limit = args.current_memory
    if args.simulate_oom:
        brief.rollout.crash_state = {
            "restarts": 6, "waiting_reason": "CrashLoopBackOff",
            "last_terminated_reason": "OOMKilled", "exit_code": 137,
            "ready": False, "pods": 2,
        }

    if brief.degraded:
        print(f"# triage degraded: {'; '.join(brief.degraded)}", file=sys.stderr)

    rca = analyze(
        brief,
        window_seconds=args.window,
        chart_version_from=args.chart_version_from,
        chart_version_to=args.chart_version_to,
    )
    # Re-validate against the contract (the trust boundary) before emitting.
    rca = RCA.model_validate_json(rca.model_dump_json())
    print(rca.model_dump_json(indent=2))
    if args.out:
        Path(args.out).write_text(rca.model_dump_json(indent=2) + "\n")
    return 0


def cmd_blast_radius(args: argparse.Namespace) -> int:
    topology = DeclaredTopologySource(_ROOT / "topology.yaml")
    deps = topology.dependents(args.service)
    print(f"{args.service} -> dependents (blast radius): {deps or 'none'}")
    return 0


def cmd_schema(_args: argparse.Namespace) -> int:
    import json

    print(json.dumps(RCA.model_json_schema(), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ballast", description="k8s-ballast RCA engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    inv = sub.add_parser("investigate", help="run triage + produce an RCA")
    inv.add_argument("--service", default="ingest")
    inv.add_argument("--namespace", default="demo")
    inv.add_argument("--healthy-memory", default="128Mi",
                     help="the known-good memory limit (for the resource diff)")
    inv.add_argument("--prometheus-url", default=os.environ.get(
        "PROMETHEUS_URL", "http://localhost:9090"))
    inv.add_argument("--alertname", default="StreamIngestCrashLooping")
    inv.add_argument("--window", type=int, default=600,
                     help="rollout<->alert correlation window in seconds")
    inv.add_argument("--chart-version-from", default=None)
    inv.add_argument("--chart-version-to", default=None)
    inv.add_argument("--repo-url", default=DEFAULT_REPO)
    inv.add_argument("--no-cluster", action="store_true",
                     help="skip kubectl (Prometheus-only triage)")
    inv.add_argument("--rollout-at", default=None,
                     help="override the rollout timestamp (ISO-8601) when no cluster")
    inv.add_argument("--current-memory", default=None,
                     help="override the observed memory limit when no cluster (e.g. 16Mi)")
    inv.add_argument("--simulate-oom", action="store_true",
                     help="inject a representative OOMKilled/CrashLoopBackOff crash state")
    inv.add_argument("--mock", action="store_true",
                     help="replay a fixture instead of touching the cluster")
    inv.add_argument("--out", default=None, help="also write the RCA JSON here")
    inv.set_defaults(func=cmd_investigate)

    br = sub.add_parser("blast-radius", help="print blast radius for a service")
    br.add_argument("service")
    br.set_defaults(func=cmd_blast_radius)

    sc = sub.add_parser("schema", help="print the RCA JSON Schema")
    sc.set_defaults(func=cmd_schema)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
