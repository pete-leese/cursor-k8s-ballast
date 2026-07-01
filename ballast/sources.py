"""Triage sources: cheap, deterministic data the engine correlates.

Two live sources back the triage step:

- ``PrometheusSource`` talks to the Prometheus HTTP API (read-only) to find the
  firing alert and its fire time, and to run supporting PromQL. In production a
  Cursor Cloud Agent would reach the same data through a read-only Prometheus /
  Grafana MCP server; the HTTP client here is the local stand-in.
- ``KubernetesSource`` shells out to ``kubectl`` to read the rollout timestamp
  (the creation time of the current ReplicaSet), the container's crash state
  (``OOMKilled`` / ``CrashLoopBackOff``) and the live resource limits.

Both degrade rather than crash: a missing source is recorded in the brief.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

import httpx


def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 / RFC-3339 timestamp into an aware UTC datetime."""
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class PrometheusSource:
    """Read-only client for the Prometheus HTTP API."""

    def __init__(self, base_url: str = "http://localhost:9090", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def active_alerts(self) -> list[dict]:
        r = self._client.get("/api/v1/alerts")
        r.raise_for_status()
        return r.json().get("data", {}).get("alerts", [])

    def firing_alert(self, alertname: str | None = None) -> dict | None:
        """Return the first firing alert, optionally filtered by name."""
        for alert in self.active_alerts():
            if alert.get("state") != "firing":
                continue
            if alertname and alert.get("labels", {}).get("alertname") != alertname:
                continue
            return alert
        return None

    def query(self, promql: str) -> list[dict]:
        r = self._client.get("/api/v1/query", params={"query": promql})
        r.raise_for_status()
        return r.json().get("data", {}).get("result", [])

    def scalar(self, promql: str) -> float | None:
        """Return the first sample value of an instant query, or None."""
        result = self.query(promql)
        if not result:
            return None
        try:
            return float(result[0]["value"][1])
        except (KeyError, IndexError, ValueError):
            return None


class KubernetesSource:
    """Reads rollout / crash state from the cluster via ``kubectl``."""

    def __init__(self, namespace: str = "ballast", context: str | None = None):
        self.namespace = namespace
        self.context = context

    def _kubectl_json(self, *args: str) -> dict:
        cmd = ["kubectl"]
        if self.context:
            cmd += ["--context", self.context]
        cmd += ["-n", self.namespace, *args, "-o", "json"]
        out = subprocess.check_output(cmd, text=True)
        return json.loads(out)

    def rollout_time(self, service: str) -> datetime | None:
        """Creation time of the newest ReplicaSet for the deployment — i.e. when
        the current rollout shipped. This is the timestamp we correlate with the
        alert. (In production the same signal comes from ArgoCD sync history.)"""
        data = self._kubectl_json("get", "rs", "-l", f"app={service}")
        newest: datetime | None = None
        for item in data.get("items", []):
            # Ignore fully scaled-down historical ReplicaSets with no desired replicas
            # only when a newer one exists; we just take the max creationTimestamp.
            ts = item.get("metadata", {}).get("creationTimestamp")
            if not ts:
                continue
            dt = _parse_ts(ts)
            if newest is None or dt > newest:
                newest = dt
        return newest

    def crash_state(self, service: str) -> dict:
        """Return a summary of the container crash state across pods:
        ``{restarts, waiting_reason, last_terminated_reason, exit_code, ready}``."""
        data = self._kubectl_json("get", "pods", "-l", f"app={service}")
        summary = {
            "restarts": 0,
            "waiting_reason": None,
            "last_terminated_reason": None,
            "exit_code": None,
            "ready": True,
            "pods": 0,
        }
        for pod in data.get("items", []):
            summary["pods"] += 1
            for cs in pod.get("status", {}).get("containerStatuses", []) or []:
                summary["restarts"] += cs.get("restartCount", 0)
                if not cs.get("ready", False):
                    summary["ready"] = False
                waiting = cs.get("state", {}).get("waiting")
                if waiting:
                    summary["waiting_reason"] = waiting.get("reason")
                term = cs.get("lastState", {}).get("terminated")
                if term:
                    summary["last_terminated_reason"] = term.get("reason")
                    summary["exit_code"] = term.get("exitCode")
        return summary

    def memory_limit(self, service: str) -> str | None:
        """Current ``resources.limits.memory`` of the deployment's container."""
        data = self._kubectl_json("get", "deploy", service)
        containers = (
            data.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [])
        )
        if not containers:
            return None
        return containers[0].get("resources", {}).get("limits", {}).get("memory")
