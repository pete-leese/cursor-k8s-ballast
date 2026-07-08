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

    _WAITING_SEVERITY = (
        "CrashLoopBackOff",
        "ImagePullBackOff",
        "ErrImagePull",
        "CreateContainerConfigError",
        "InvalidImageName",
    )

    @classmethod
    def _normalize_terminated(cls, term: dict) -> tuple[str | None, int | None]:
        reason = term.get("reason")
        exit_code = term.get("exitCode")
        if exit_code == 137 and reason in (None, "Unknown", "Error"):
            reason = "OOMKilled"
        return reason, exit_code

    @classmethod
    def _pick_waiting(cls, reasons: list[str]) -> str | None:
        if not reasons:
            return None
        for preferred in cls._WAITING_SEVERITY:
            if preferred in reasons:
                return preferred
        return reasons[0]

    def crash_state(self, service: str) -> dict:
        """Return a summary of the container crash state across pods.

        ``display_state`` reflects the *current* workload health (e.g. Running,
        CrashLoopBackOff). ``last_terminated_reason`` is kept for RCA and
        normalises exit 137 to OOMKilled even when Kubernetes reports Unknown.
        """
        data = self._kubectl_json("get", "pods", "-l", f"app={service}")
        summary = {
            "restarts": 0,
            "waiting_reason": None,
            "last_terminated_reason": None,
            "exit_code": None,
            "ready": True,
            "pods": 0,
            "ready_pods": 0,
            "display_state": "Unknown",
        }
        waiting_reasons: list[str] = []
        terminated_reasons: list[str] = []
        exit_codes: list[int] = []
        running = 0

        for pod in data.get("items", []):
            summary["pods"] += 1
            pod_ready = True
            for cs in pod.get("status", {}).get("containerStatuses", []) or []:
                summary["restarts"] += cs.get("restartCount", 0)
                if not cs.get("ready", False):
                    summary["ready"] = False
                    pod_ready = False

                state = cs.get("state", {}) or {}
                waiting = state.get("waiting")
                if waiting:
                    reason = waiting.get("reason")
                    if reason:
                        waiting_reasons.append(reason)
                elif state.get("running"):
                    running += 1

                current_term = state.get("terminated")
                if current_term:
                    reason, exit_code = self._normalize_terminated(current_term)
                    if reason:
                        terminated_reasons.append(reason)
                    if exit_code is not None:
                        exit_codes.append(exit_code)

                term = cs.get("lastState", {}).get("terminated")
                if term:
                    reason, exit_code = self._normalize_terminated(term)
                    if reason:
                        terminated_reasons.append(reason)
                    if exit_code is not None:
                        exit_codes.append(exit_code)

            if pod_ready:
                summary["ready_pods"] += 1

        summary["waiting_reason"] = self._pick_waiting(waiting_reasons)
        if terminated_reasons:
            summary["last_terminated_reason"] = (
                "OOMKilled"
                if "OOMKilled" in terminated_reasons
                else terminated_reasons[-1]
            )
        if exit_codes:
            summary["exit_code"] = 137 if 137 in exit_codes else exit_codes[-1]

        if summary["waiting_reason"]:
            summary["display_state"] = summary["waiting_reason"]
        elif summary["pods"] and summary["ready"] and running == summary["pods"]:
            summary["display_state"] = "Running"
        elif summary["pods"] and summary["ready_pods"] == 0:
            summary["display_state"] = summary["last_terminated_reason"] or "NotReady"
        elif not summary["ready"]:
            summary["display_state"] = "NotReady"
        else:
            summary["display_state"] = "Running"

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


class ArgoCDSource:
    """Reads ArgoCD Application sync/health state via ``kubectl``."""

    def __init__(self, namespace: str = "argocd", context: str | None = None):
        self.namespace = namespace
        self.context = context

    def _kubectl(self, *args: str, json_out: bool = True) -> dict | str:
        cmd = ["kubectl"]
        if self.context:
            cmd += ["--context", self.context]
        cmd += ["-n", self.namespace, *args]
        if json_out:
            cmd += ["-o", "json"]
        out = subprocess.check_output(cmd, text=True)
        return json.loads(out) if json_out else out

    def application_context(self, name: str, *, event_limit: int = 8) -> dict | None:
        """Return a dict suitable for ``ArgoCDContext`` construction."""
        try:
            app = self._kubectl("get", "application", name)
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            return None

        status = app.get("status", {})
        sync = status.get("sync", {})
        health = status.get("health", {})
        op = status.get("operationState", {})

        revisions = sync.get("revisions") or []
        revision = revisions[0] if revisions else sync.get("revision")

        sources = sync.get("comparedTo", {}).get("sources") or []
        target_revision = None
        if sources:
            target_revision = sources[0].get("targetRevision")

        history = []
        for entry in status.get("history", [])[:5]:
            revs = entry.get("revisions") or []
            history.append(
                {
                    "id": entry.get("id"),
                    "deployed_at": entry.get("deployedAt"),
                    "revision": revs[0] if revs else entry.get("revision"),
                }
            )

        sync_resources = []
        for res in (op.get("syncResult", {}) or {}).get("resources", [])[:12]:
            sync_resources.append(
                {
                    "kind": res.get("kind", ""),
                    "name": res.get("name", ""),
                    "namespace": res.get("namespace"),
                    "status": res.get("status") or res.get("hookPhase"),
                    "message": res.get("message"),
                }
            )

        events = self.cluster_events(name, limit=event_limit)

        return {
            "application": name,
            "sync_status": sync.get("status"),
            "health_status": health.get("status"),
            "revision": revision,
            "target_revision": target_revision,
            "last_sync_started": op.get("startedAt"),
            "last_sync_finished": op.get("finishedAt"),
            "last_sync_phase": op.get("phase"),
            "last_sync_message": op.get("message"),
            "health_transition": health.get("lastTransitionTime"),
            "history": history,
            "sync_resources": sync_resources,
            "events": events,
        }

    def cluster_events(self, app_name: str, *, limit: int = 8) -> list[dict]:
        try:
            data = self._kubectl(
                "get",
                "events",
                "--field-selector",
                f"involvedObject.name={app_name}",
            )
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            return []

        items = data.get("items", [])
        items.sort(
            key=lambda e: e.get("lastTimestamp") or e.get("eventTime") or "",
            reverse=True,
        )
        out = []
        for ev in items[:limit]:
            ts = ev.get("lastTimestamp") or ev.get("eventTime") or ""
            out.append(
                {
                    "timestamp": ts,
                    "type": ev.get("type", "Normal"),
                    "reason": ev.get("reason", ""),
                    "message": ev.get("message", ""),
                }
            )
        return out
