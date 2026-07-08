"""In-memory store of investigations for the Ballast console API."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from .brief import InvestigationBrief
from .contract import RCA
from .investigator import InvestigationEvent


class InvestigationStatus(str, Enum):
    queued = "queued"
    triaging = "triaging"
    investigating = "investigating"
    complete = "complete"
    failed = "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class InvestigationRecord(BaseModel):
    id: str
    alertname: str
    service: str
    status: InvestigationStatus = InvestigationStatus.queued
    created_at: str = Field(default_factory=_now)
    brief: InvestigationBrief | None = None
    events: list[InvestigationEvent] = []
    rca: RCA | None = None
    error: str | None = None


class InvestigationStore:
    def __init__(self) -> None:
        self._records: dict[str, InvestigationRecord] = {}
        self._lock = threading.Lock()

    def create(self, record: InvestigationRecord) -> None:
        with self._lock:
            self._records[record.id] = record

    def get(self, investigation_id: str) -> InvestigationRecord | None:
        with self._lock:
            return self._records.get(investigation_id)

    def list(self) -> list[InvestigationRecord]:
        with self._lock:
            return sorted(
                self._records.values(), key=lambda r: r.created_at, reverse=True
            )

    def update(self, investigation_id: str, **fields) -> None:
        with self._lock:
            record = self._records.get(investigation_id)
            if record is None:
                return
            for key, value in fields.items():
                setattr(record, key, value)

    def append_event(self, investigation_id: str, event: InvestigationEvent) -> None:
        with self._lock:
            record = self._records.get(investigation_id)
            if record is not None:
                if event.timestamp is None:
                    event = event.model_copy(update={"timestamp": _now()})
                record.events.append(event)

    def has_active_for_alert(self, alertname: str, service: str) -> bool:
        with self._lock:
            for record in self._records.values():
                if (
                    record.alertname == alertname
                    and record.service == service
                    and record.status
                    in (
                        InvestigationStatus.queued,
                        InvestigationStatus.triaging,
                        InvestigationStatus.investigating,
                    )
                ):
                    return True
            return False


STORE = InvestigationStore()
