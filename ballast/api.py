"""FastAPI: alert webhook, investigation API, and optional alert watcher."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from .brief import AlertContext
from .orchestrator import run_investigation
from .preflight import assess_investigation_readiness, cluster_overview
from .rca_chat import chat_available, reply as rca_chat_reply, resolve_investigation_agent
from .remediate import spawn_remediation, reconcile_remediation
from .sources import ArgoCDSource, KubernetesSource, PrometheusSource
from .store import STORE, InvestigationRecord, InvestigationStatus

app = FastAPI(title="Ballast API")

_WEBHOOK_SECRET = os.environ.get("BALLAST_WEBHOOK_SECRET", "")
_DEFAULT_ALERT = os.environ.get("BALLAST_ALERTNAME", "StreamIngestCrashLooping")
_DEFAULT_SERVICE = os.environ.get("BALLAST_SERVICE", "ingest")
_WATCH_ALERTS = os.environ.get("BALLAST_ALERT_WATCH", "0") == "1"
_WATCH_INTERVAL = int(os.environ.get("BALLAST_ALERT_WATCH_INTERVAL", "15"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _spawn(investigation_id: str, alert: AlertContext, service: str) -> None:
    threading.Thread(
        target=run_investigation,
        args=(investigation_id, alert, service),
        daemon=True,
    ).start()


def _start(alertname: str, service: str, alert: AlertContext) -> str | None:
    fired_at = alert.fired_at
    # Idempotency for an active incident: never spawn a second investigation
    # when one is already running, already covers this alert episode, or was
    # just created for the same alert+service. The console triggers with a
    # fresh `_now()` episode whenever no alert is firing yet, so episode-exact
    # matching alone would let each completed run be followed by a brand-new
    # one on the next tick — the `find_recent_for_alert` fallback closes that.
    existing = (
        STORE.find_active_for_alert(alertname, service)
        or STORE.find_for_alert_episode(alertname, service, fired_at)
        or STORE.find_recent_for_alert(alertname, service)
    )
    if existing is not None:
        return existing.id
    investigation_id = STORE.allocate_incident_id()
    STORE.create(
        InvestigationRecord(
            id=investigation_id,
            alertname=alertname,
            service=service,
            alert_fired_at=fired_at,
        )
    )
    _spawn(investigation_id, alert, service)
    return investigation_id


def _watch_alerts() -> None:
    prom_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    while True:
        try:
            prom = PrometheusSource(prom_url)
            alert = prom.firing_alert(_DEFAULT_ALERT, namespace="demo")
            if not alert:
                time.sleep(_WATCH_INTERVAL)
                continue
            labels = alert.get("labels", {})
            service = (
                labels.get("container")
                or labels.get("service")
                or _DEFAULT_SERVICE
            )
            pf = assess_investigation_readiness(
                _DEFAULT_ALERT, service, namespace="demo"
            )
            if not pf.ready:
                time.sleep(_WATCH_INTERVAL)
                continue
            ctx = AlertContext(
                alertname=_DEFAULT_ALERT,
                fired_at=alert.get("activeAt", _now()),
                expr=alert.get("annotations", {}).get("description"),
                severity=labels.get("severity"),
                labels=labels,
            )
            _start(_DEFAULT_ALERT, service, ctx)
        except Exception:
            pass
        time.sleep(_WATCH_INTERVAL)


@app.on_event("startup")
def _startup() -> None:
    if _WATCH_ALERTS:
        threading.Thread(target=_watch_alerts, daemon=True).start()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/webhook/alert")
async def webhook_alert(
    request: Request, authorization: str | None = Header(default=None)
):
    if _WEBHOOK_SECRET and authorization != f"Bearer {_WEBHOOK_SECRET}":
        raise HTTPException(status_code=401, detail="bad or missing webhook secret")

    payload = await request.json()
    started: list[str] = []
    for alert in payload.get("alerts", []):
        if alert.get("status") != "firing":
            continue
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alertname = labels.get("alertname", "UnknownAlert")
        service = labels.get("service", _DEFAULT_SERVICE)
        ctx = AlertContext(
            alertname=alertname,
            fired_at=alert.get("startsAt", _now()),
            expr=annotations.get("description"),
            severity=labels.get("severity"),
            labels=labels,
        )
        investigation_id = _start(alertname, service, ctx)
        if investigation_id:
            started.append(investigation_id)
    return {"accepted": len(started), "investigation_ids": started}


class TriggerBody(BaseModel):
    alertname: str = _DEFAULT_ALERT
    service: str = _DEFAULT_SERVICE
    fired_at: str | None = None


@app.get("/cluster/overview")
def get_cluster_overview(service: str = _DEFAULT_SERVICE):
    return cluster_overview(service)


@app.get("/investigations/preflight")
def investigation_preflight(
    alertname: str = _DEFAULT_ALERT,
    service: str = _DEFAULT_SERVICE,
):
    return assess_investigation_readiness(alertname, service).model_dump()


@app.post("/investigations")
def trigger(body: TriggerBody):
    pf = assess_investigation_readiness(body.alertname, body.service)
    if not pf.ready:
        detail = {
            "ready": False,
            "cluster_healthy": pf.cluster_healthy,
            "alert_firing": pf.alert_firing,
            "incident_detected": pf.incident_detected,
            "signals": pf.signals,
            "blockers": pf.blockers,
            "hint": pf.hint,
            "existing_investigation_id": pf.existing_investigation_id,
        }
        raise HTTPException(status_code=409, detail=detail)
    ctx = AlertContext(
        alertname=body.alertname,
        fired_at=body.fired_at or pf.alert_fired_at or _now(),
        observed=bool(pf.alert_firing or body.fired_at),
        severity="warning",
    )
    investigation_id = _start(body.alertname, body.service, ctx)
    return {"id": investigation_id, "preflight": pf.model_dump()}


@app.get("/investigations")
def list_investigations():
    return [
        {
            "id": r.id,
            "alertname": r.alertname,
            "service": r.service,
            "status": r.status.value,
            "created_at": r.created_at,
        }
        for r in STORE.list()
    ]


@app.delete("/investigations")
def clear_investigations():
    cleared = STORE.clear_all()
    return {"cleared": cleared}


@app.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: str):
    record = STORE.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not found")
    # Self-heal: Cursor may open the PR without the SDK returning prUrl.
    if record.github_issue_url and not record.remediation_pr_url:
        reconcile_remediation(investigation_id)
        record = STORE.get(investigation_id) or record
    return record


@app.post("/investigations/{investigation_id}/remediate")
def trigger_remediation(investigation_id: str):
    record = STORE.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not found")
    if record.rca is None:
        raise HTTPException(status_code=400, detail="RCA not ready")
    if record.remediation_pr_url:
        return {
            "status": "complete",
            "github_issue_url": record.github_issue_url,
            "remediation_pr_url": record.remediation_pr_url,
            "reused": True,
        }
    # Reuse issue/PR from a prior investigation of the same alert episode.
    prior = STORE.find_remediation_for_episode(
        record.alertname, record.service, record.alert_fired_at
    )
    if prior and prior.id != investigation_id and (
        prior.github_issue_url or prior.remediation_pr_url
    ):
        STORE.update(
            investigation_id,
            github_issue_url=prior.github_issue_url,
            remediation_issue_created_at=prior.remediation_issue_created_at,
            remediation_pr_url=prior.remediation_pr_url,
            remediation_pr_opened_at=prior.remediation_pr_opened_at,
            remediation_pr_merged_at=prior.remediation_pr_merged_at,
            remediation_agent_id=prior.remediation_agent_id,
            remediation_status="complete",
            remediation_error=None,
        )
        return {
            "status": "complete",
            "github_issue_url": prior.github_issue_url,
            "remediation_pr_url": prior.remediation_pr_url,
            "reused": True,
            "from_investigation_id": prior.id,
        }
    if record.remediation_status in ("queued", "creating_issue", "launching_agent"):
        return {
            "status": record.remediation_status,
            "github_issue_url": record.github_issue_url,
            "remediation_pr_url": record.remediation_pr_url,
        }
    STORE.update(investigation_id, remediation_status="queued", remediation_error=None)
    spawn_remediation(investigation_id, record.rca)
    return {"status": "queued", "investigation_id": investigation_id}


@app.get("/investigations/{investigation_id}/artifacts/{name}")
def get_investigation_artifact(investigation_id: str, name: str):
    if STORE.get(investigation_id) is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    data = STORE.get_artifact(investigation_id, name)
    if data is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    media = "image/png" if name.endswith(".png") else "application/octet-stream"
    return Response(content=data, media_type=media)


class ChatRequest(BaseModel):
    message: str


@app.get("/investigations/{investigation_id}/chat/status")
def chat_status(investigation_id: str):
    record = STORE.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "available": chat_available(),
        "provider": "cursor",
        "message_count": len(record.chat_messages),
        "cursor_agent_id": resolve_investigation_agent(record) or record.chat_agent_id,
        "model": os.environ.get("CURSOR_MODEL", "composer-2.5"),
    }


@app.get("/investigations/{investigation_id}/chat")
def get_chat_history(investigation_id: str):
    record = STORE.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"messages": record.chat_messages}


@app.post("/investigations/{investigation_id}/chat")
def post_chat(investigation_id: str, body: ChatRequest):
    record = STORE.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not found")
    if record.rca is None:
        raise HTTPException(status_code=400, detail="RCA not ready")
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="empty message")
    if not chat_available():
        raise HTTPException(
            status_code=503,
            detail="Chat not configured — set CURSOR_API_KEY in .env",
        )

    argocd_ctx = None
    kube_ctx = None
    try:
        argocd_ctx = ArgoCDSource().application_context(record.service)
    except Exception:
        pass
    try:
        kube = KubernetesSource(
            namespace=record.brief.namespace if record.brief else "demo"
        )
        kube_ctx = {
            "crash_state": kube.crash_state(record.service),
            "memory_limit": kube.memory_limit(record.service),
        }
    except Exception:
        pass

    STORE.append_chat(investigation_id, "user", body.message.strip())
    record = STORE.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        answer = rca_chat_reply(
            record,
            body.message.strip(),
            argocd=argocd_ctx,
            kube=kube_ctx,
            on_chat_agent_created=lambda aid: STORE.update(
                investigation_id, chat_agent_id=aid
            ),
        )
    except Exception as exc:
        # Drop the orphaned user turn so a failed request doesn't pollute history.
        msgs = list(record.chat_messages)
        if msgs and msgs[-1].role == "user":
            STORE.update(investigation_id, chat_messages=msgs[:-1])
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    STORE.append_chat(investigation_id, "assistant", answer)
    updated = STORE.get(investigation_id)
    return {
        "reply": answer,
        "messages": updated.chat_messages if updated else [],
    }


@app.get("/argocd/applications/{service}")
def get_argocd_application(service: str):
    try:
        argo = ArgoCDSource()
        ctx = argo.application_context(service)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if ctx is None:
        raise HTTPException(status_code=404, detail="application not found")
    return ctx


@app.get("/kubernetes/services/{service}")
def get_service_state(service: str, namespace: str = "demo"):
    try:
        kube = KubernetesSource(namespace=namespace)
        crash = kube.crash_state(service)
        mem = kube.memory_limit(service)
        return {
            "service": service,
            "namespace": namespace,
            "crash_state": crash,
            "memory_limit": mem,
            "available": crash.get("pods", 0) > 0 or mem is not None,
        }
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503, detail="kubectl not found — is the cluster tooling installed?"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
