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


def _normalize_ts(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("Z", "+00:00")


class ChatMessage(BaseModel):
    role: str  # user | assistant
    content: str
    timestamp: str = Field(default_factory=_now)


class InvestigationRecord(BaseModel):
    id: str
    alertname: str
    service: str
    alert_fired_at: str | None = None
    status: InvestigationStatus = InvestigationStatus.queued
    created_at: str = Field(default_factory=_now)
    brief: InvestigationBrief | None = None
    events: list[InvestigationEvent] = []
    rca: RCA | None = None
    error: str | None = None
    artifact_names: list[str] = []
    chat_messages: list[ChatMessage] = []
    cursor_agent_id: str | None = None
    chat_agent_id: str | None = None
    remediation_status: str | None = None
    remediation_queued_at: str | None = None
    github_issue_url: str | None = None
    remediation_issue_created_at: str | None = None
    remediation_pr_url: str | None = None
    remediation_pr_opened_at: str | None = None
    remediation_pr_merged_at: str | None = None
    remediation_agent_id: str | None = None
    remediation_error: str | None = None


class InvestigationStore:
    def __init__(self) -> None:
        self._records: dict[str, InvestigationRecord] = {}
        self._artifacts: dict[str, dict[str, bytes]] = {}
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

    def put_artifact(self, investigation_id: str, name: str, data: bytes) -> None:
        with self._lock:
            self._artifacts.setdefault(investigation_id, {})[name] = data
            record = self._records.get(investigation_id)
            if record is not None and name not in record.artifact_names:
                record.artifact_names.append(name)

    def get_artifact(self, investigation_id: str, name: str) -> bytes | None:
        with self._lock:
            return self._artifacts.get(investigation_id, {}).get(name)

    def append_chat(
        self, investigation_id: str, role: str, content: str
    ) -> ChatMessage | None:
        with self._lock:
            record = self._records.get(investigation_id)
            if record is None:
                return None
            msg = ChatMessage(role=role, content=content)
            record.chat_messages.append(msg)
            return msg

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

    def _episode_ts(self, record: InvestigationRecord) -> str | None:
        if record.alert_fired_at:
            return _normalize_ts(record.alert_fired_at)
        brief = record.brief
        if brief and brief.alert and brief.alert.fired_at:
            return _normalize_ts(brief.alert.fired_at)
        return None

    def has_for_alert_episode(
        self, alertname: str, service: str, fired_at: str | None
    ) -> bool:
        """True if this alert episode was already investigated (any terminal status)."""
        episode = _normalize_ts(fired_at)
        with self._lock:
            for record in self._records.values():
                if record.alertname != alertname or record.service != service:
                    continue
                if record.status in (
                    InvestigationStatus.queued,
                    InvestigationStatus.triaging,
                    InvestigationStatus.investigating,
                ):
                    return True
                if episode and self._episode_ts(record) == episode:
                    return True
            return False

    def find_for_alert_episode(
        self, alertname: str, service: str, fired_at: str | None
    ) -> InvestigationRecord | None:
        episode = _normalize_ts(fired_at)
        with self._lock:
            for record in sorted(
                self._records.values(), key=lambda r: r.created_at, reverse=True
            ):
                if record.alertname != alertname or record.service != service:
                    continue
                if episode and self._episode_ts(record) == episode:
                    return record
            return None


STORE = InvestigationStore()
