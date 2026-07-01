"""FastAPI: alert webhook, investigation API, and optional alert watcher."""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from .brief import AlertContext
from .orchestrator import run_investigation
from .sources import PrometheusSource
from .store import STORE, InvestigationRecord, InvestigationStatus

app = FastAPI(title="Ballast API")

_WEBHOOK_SECRET = os.environ.get("BALLAST_WEBHOOK_SECRET", "")
_DEFAULT_ALERT = os.environ.get("BALLAST_ALERTNAME", "BallastServiceCrashLooping")
_DEFAULT_SERVICE = os.environ.get("BALLAST_SERVICE", "payments")
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


def _start(alertname: str, service: str, alert: AlertContext) -> str:
    investigation_id = (
        f"inv-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    )
    STORE.create(
        InvestigationRecord(id=investigation_id, alertname=alertname, service=service)
    )
    _spawn(investigation_id, alert, service)
    return investigation_id


def _watch_alerts() -> None:
    prom_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    while True:
        try:
            prom = PrometheusSource(prom_url)
            alert = prom.firing_alert(_DEFAULT_ALERT)
            if alert:
                labels = alert.get("labels", {})
                service = labels.get("service", _DEFAULT_SERVICE)
                if not STORE.has_active_for_alert(_DEFAULT_ALERT, service):
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
        started.append(_start(alertname, service, ctx))
    return {"accepted": len(started), "investigation_ids": started}


class TriggerBody(BaseModel):
    alertname: str = _DEFAULT_ALERT
    service: str = _DEFAULT_SERVICE
    fired_at: str | None = None


@app.post("/investigations")
def trigger(body: TriggerBody):
    ctx = AlertContext(
        alertname=body.alertname,
        fired_at=body.fired_at or _now(),
        severity="warning",
    )
    investigation_id = _start(body.alertname, body.service, ctx)
    return {"id": investigation_id}


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


@app.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: str):
    record = STORE.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not found")
    return record
