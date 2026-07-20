"""Durable investigation store for the Ballast console API.

Records and chat live in ``.ballast/investigations.json``; screenshot artifacts
are files under ``.ballast/artifacts/<id>/``. Survives API restarts so the same
alert episode is not re-investigated and remediation does not open duplicate
GitHub issues / PRs.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from .brief import InvestigationBrief
from .contract import RCA
from .investigator import InvestigationEvent

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DATA_DIR = _ROOT / ".ballast"
_INCIDENT_PREFIX = os.environ.get("BALLAST_INCIDENT_PREFIX", "INC-")


def _data_dir() -> Path:
    raw = os.environ.get("BALLAST_DATA_DIR", "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_DATA_DIR


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
    cursor_run_url: str | None = None
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


def _parse_incident_number(investigation_id: str) -> int | None:
    """Extract the integer from ``INC-0042``-style ids; None for legacy ids."""
    prefix = _INCIDENT_PREFIX
    if not investigation_id.startswith(prefix):
        return None
    rest = investigation_id[len(prefix) :]
    if not rest.isdigit():
        return None
    return int(rest)


class InvestigationStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or _data_dir()
        self._index_path = self._data_dir / "investigations.json"
        self._artifacts_dir = self._data_dir / "artifacts"
        self._records: dict[str, InvestigationRecord] = {}
        self._artifacts: dict[str, dict[str, bytes]] = {}
        self._next_incident_number: int = 1
        self._lock = threading.RLock()
        self._load()

    def _ensure_dirs(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        self._ensure_dirs()
        if not self._index_path.exists():
            return
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        items = raw.get("investigations") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return
        max_num = 0
        for item in items:
            try:
                record = InvestigationRecord.model_validate(item)
            except Exception:
                continue
            self._records[record.id] = record
            n = _parse_incident_number(record.id)
            if n is not None and n > max_num:
                max_num = n
            # Hydrate artifact bytes from disk when present.
            art_dir = self._artifacts_dir / record.id
            if art_dir.is_dir():
                blob: dict[str, bytes] = {}
                for path in art_dir.iterdir():
                    if path.is_file():
                        try:
                            blob[path.name] = path.read_bytes()
                        except OSError:
                            continue
                if blob:
                    self._artifacts[record.id] = blob
                    for name in blob:
                        if name not in record.artifact_names:
                            record.artifact_names.append(name)
        persisted_next = 0
        if isinstance(raw, dict):
            try:
                persisted_next = int(raw.get("next_incident_number") or 0)
            except (TypeError, ValueError):
                persisted_next = 0
        self._next_incident_number = max(persisted_next, max_num + 1, 1)

    def _persist_unlocked(self) -> None:
        self._ensure_dirs()
        payload = {
            "version": 1,
            "updated_at": _now(),
            "next_incident_number": self._next_incident_number,
            "investigations": [
                r.model_dump(mode="json")
                for r in sorted(
                    self._records.values(), key=lambda x: x.created_at, reverse=True
                )
            ],
        }
        tmp = self._index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._index_path)

    def _persist(self) -> None:
        with self._lock:
            self._persist_unlocked()

    def allocate_incident_id(self) -> str:
        """Allocate the next unique incident ticket id (e.g. ``INC-0042``)."""
        with self._lock:
            n = self._next_incident_number
            self._next_incident_number = n + 1
            # Persist the counter even before the record is created, so a crash
            # mid-create does not reuse the number.
            self._persist_unlocked()
            return f"{_INCIDENT_PREFIX}{n:04d}"

    def create(self, record: InvestigationRecord) -> None:
        with self._lock:
            self._records[record.id] = record
            self._persist_unlocked()

    def get(self, investigation_id: str) -> InvestigationRecord | None:
        with self._lock:
            return self._records.get(investigation_id)

    def list(self) -> list[InvestigationRecord]:
        with self._lock:
            return sorted(
                self._records.values(), key=lambda r: r.created_at, reverse=True
            )

    def clear_all(self) -> int:
        """Remove every investigation record and on-disk artifacts. Returns count cleared."""
        with self._lock:
            count = len(self._records)
            self._records.clear()
            self._artifacts.clear()
            self._persist_unlocked()
            if self._artifacts_dir.is_dir():
                for child in self._artifacts_dir.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    elif child.is_file():
                        try:
                            child.unlink()
                        except OSError:
                            pass
            return count

    def update(self, investigation_id: str, **fields) -> None:
        with self._lock:
            record = self._records.get(investigation_id)
            if record is None:
                return
            for key, value in fields.items():
                setattr(record, key, value)
            self._persist_unlocked()

    def append_event(self, investigation_id: str, event: InvestigationEvent) -> None:
        with self._lock:
            record = self._records.get(investigation_id)
            if record is not None:
                if event.timestamp is None:
                    event = event.model_copy(update={"timestamp": _now()})
                record.events.append(event)
                self._persist_unlocked()

    def put_artifact(self, investigation_id: str, name: str, data: bytes) -> None:
        with self._lock:
            self._artifacts.setdefault(investigation_id, {})[name] = data
            record = self._records.get(investigation_id)
            if record is not None and name not in record.artifact_names:
                record.artifact_names.append(name)
            art_dir = self._artifacts_dir / investigation_id
            art_dir.mkdir(parents=True, exist_ok=True)
            (art_dir / name).write_bytes(data)
            if record is not None:
                self._persist_unlocked()

    def get_artifact(self, investigation_id: str, name: str) -> bytes | None:
        with self._lock:
            cached = self._artifacts.get(investigation_id, {}).get(name)
            if cached is not None:
                return cached
            path = self._artifacts_dir / investigation_id / name
            if path.is_file():
                try:
                    data = path.read_bytes()
                except OSError:
                    return None
                self._artifacts.setdefault(investigation_id, {})[name] = data
                return data
            return None

    def append_chat(
        self, investigation_id: str, role: str, content: str
    ) -> ChatMessage | None:
        with self._lock:
            record = self._records.get(investigation_id)
            if record is None:
                return None
            msg = ChatMessage(role=role, content=content)
            record.chat_messages.append(msg)
            self._persist_unlocked()
            return msg

    def has_active_for_alert(self, alertname: str, service: str) -> bool:
        return self.find_active_for_alert(alertname, service) is not None

    def find_active_for_alert(
        self, alertname: str, service: str
    ) -> InvestigationRecord | None:
        with self._lock:
            for record in sorted(
                self._records.values(), key=lambda r: r.created_at, reverse=True
            ):
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
                    return record
            return None

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
                if not episode and record.status in (
                    InvestigationStatus.queued,
                    InvestigationStatus.triaging,
                    InvestigationStatus.investigating,
                ):
                    return record
            return None

    def find_recent_for_service(
        self, service: str, *, within_seconds: int = 3600
    ) -> InvestigationRecord | None:
        """Newest investigation for ``service`` created within ``within_seconds``."""
        cutoff = datetime.now(timezone.utc).timestamp() - within_seconds
        with self._lock:
            for record in sorted(
                self._records.values(), key=lambda r: r.created_at, reverse=True
            ):
                if record.service != service:
                    continue
                try:
                    ts = datetime.fromisoformat(
                        record.created_at.replace("Z", "+00:00")
                    ).timestamp()
                except ValueError:
                    continue
                if ts >= cutoff:
                    return record
            return None

    def find_recent_for_alert(
        self, alertname: str, service: str, *, within_seconds: int = 1800
    ) -> InvestigationRecord | None:
        """Newest non-failed investigation for this alert+service in the window.

        Backs POST idempotency for an active incident. Episode-exact dedup keys
        on the firing-alert timestamp, but the console triggers with a fresh
        ``_now()`` whenever no alert is firing yet (CrashLoop-only / pending
        ``for:`` window), so a completed run would otherwise be followed by a
        brand-new one on the next trigger. Matching any recent run for the same
        alert+service collapses those repeat submits onto the first record.
        Failed runs are skipped so a genuine retry can still start.
        """
        cutoff = datetime.now(timezone.utc).timestamp() - within_seconds
        with self._lock:
            for record in sorted(
                self._records.values(), key=lambda r: r.created_at, reverse=True
            ):
                if record.alertname != alertname or record.service != service:
                    continue
                if record.status == InvestigationStatus.failed:
                    continue
                try:
                    ts = datetime.fromisoformat(
                        record.created_at.replace("Z", "+00:00")
                    ).timestamp()
                except ValueError:
                    continue
                if ts >= cutoff:
                    return record
            return None

    def find_remediation_for_episode(
        self, alertname: str, service: str, fired_at: str | None
    ) -> InvestigationRecord | None:
        """Return the newest episode record that already has an issue and/or PR."""
        episode = _normalize_ts(fired_at)
        with self._lock:
            for record in sorted(
                self._records.values(), key=lambda r: r.created_at, reverse=True
            ):
                if record.alertname != alertname or record.service != service:
                    continue
                if not (record.github_issue_url or record.remediation_pr_url):
                    continue
                if episode and self._episode_ts(record) and self._episode_ts(record) != episode:
                    continue
                return record
            return None


STORE = InvestigationStore()
