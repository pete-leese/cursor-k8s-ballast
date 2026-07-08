"""The investigator seam: brief in, a stream of events out, ending in a validated RCA."""

from __future__ import annotations

import json
import os
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel, ValidationError

from .brief import InvestigationBrief
from .contract import RCA, GeneratedBy
from .engine import analyze

_ROOT = Path(__file__).resolve().parent.parent


class InvestigationEvent(BaseModel):
    type: str  # status | thinking | tool_call | assistant | rca | error
    name: str | None = None
    status: str | None = None
    text: str | None = None
    rca: RCA | None = None
    timestamp: str | None = None


class Investigator(ABC):
    @abstractmethod
    def investigate(self, brief: InvestigationBrief) -> Iterator[InvestigationEvent]:
        ...


class EngineInvestigator(Investigator):
    """Deterministic on-cluster analyzer — the default for the console demo."""

    def investigate(self, brief: InvestigationBrief) -> Iterator[InvestigationEvent]:
        yield InvestigationEvent(type="status", text="Assembling triage brief")
        yield InvestigationEvent(
            type="tool_call",
            name="rollout_status",
            status=f"{brief.namespace}/{brief.service}",
        )
        yield InvestigationEvent(
            type="tool_call",
            name="get_firing_alerts",
            status=brief.alert.alertname,
        )
        yield InvestigationEvent(type="status", text="Running deterministic RCA engine")
        try:
            rca = analyze(brief)
            rca = RCA.model_validate_json(rca.model_dump_json())
        except Exception as exc:
            yield InvestigationEvent(type="error", text=str(exc))
            return
        yield InvestigationEvent(type="rca", rca=rca)


class MockInvestigator(Investigator):
    """Replays a canned-but-realistic RCA from a fixture."""

    def __init__(self, fixture_path: str | Path | None = None) -> None:
        self.fixture = Path(fixture_path or _ROOT / "fixtures" / "rca_payments.json")

    def rca(self, *, service: str, investigation_id: str) -> RCA:
        rca = RCA.model_validate_json(self.fixture.read_text())
        rca.generated_by = GeneratedBy.mock
        rca.investigation_id = investigation_id
        rca.service = service
        return rca

    def investigate(self, brief: InvestigationBrief) -> Iterator[InvestigationEvent]:
        yield InvestigationEvent(type="status", text="Replaying fixture investigation")
        yield InvestigationEvent(
            type="tool_call",
            name="read_file",
            status="deploy/services/payments.values.yaml",
        )
        yield InvestigationEvent(
            type="tool_call",
            name="rollout_status",
            status=f"{brief.namespace}/{brief.service}",
        )
        try:
            rca = RCA.model_validate_json(self.fixture.read_text())
        except (OSError, ValidationError) as exc:
            yield InvestigationEvent(type="error", text=f"fixture invalid: {exc}")
            return
        rca.generated_by = GeneratedBy.mock
        rca.investigation_id = brief.investigation_id
        rca.service = brief.service
        yield InvestigationEvent(type="rca", rca=rca)


class CursorInvestigator(Investigator):
    """Runs a real Cursor cloud agent via the Node sdk-runner."""

    def __init__(
        self,
        runner_dir: str | Path | None = None,
        repo_url: str | None = None,
        repo_ref: str | None = None,
        model: str | None = None,
    ) -> None:
        self.runner_dir = Path(runner_dir or _ROOT / "sdk-runner")
        self.repo_url = repo_url or os.environ.get(
            "CURSOR_TARGET_REPO", "https://github.com/pete-leese/cursor-k8s-ballast"
        )
        self.repo_ref = repo_ref or os.environ.get("CURSOR_TARGET_REF", "main")
        self.model = model or os.environ.get("CURSOR_MODEL", "composer-2")

    def investigate(self, brief: InvestigationBrief) -> Iterator[InvestigationEvent]:
        sdk_pkg = self.runner_dir / "node_modules" / "@cursor" / "sdk"
        if not sdk_pkg.exists():
            yield InvestigationEvent(
                type="error",
                text="sdk-runner not installed — run: task sdk:install",
            )
            return
        if not os.environ.get("CURSOR_API_KEY"):
            yield InvestigationEvent(
                type="error",
                text="CURSOR_API_KEY not set — add it to .env and restart the console",
            )
            return

        env = {
            **os.environ,
            "CURSOR_TARGET_REPO": self.repo_url,
            "CURSOR_TARGET_REF": self.repo_ref,
            "CURSOR_MODEL": self.model,
        }
        try:
            proc = subprocess.Popen(
                ["node", "run.mjs"],
                cwd=self.runner_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
        except FileNotFoundError as exc:
            yield InvestigationEvent(type="error", text=f"node/runner not found: {exc}")
            return

        assert proc.stdin and proc.stdout and proc.stderr
        schema = (_ROOT / "schema" / "rca.schema.json").read_text()
        proc.stdin.write(json.dumps({"prompt": brief.to_agent_prompt(schema)}))
        proc.stdin.close()

        saw_event = False
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("type") == "rca":
                try:
                    rca = RCA.model_validate(evt["data"])
                except ValidationError as exc:
                    yield InvestigationEvent(
                        type="error", text=f"RCA failed contract validation: {exc}"
                    )
                    continue
                rca.generated_by = GeneratedBy.cursor
                saw_event = True
                yield InvestigationEvent(type="rca", rca=rca)
            else:
                saw_event = True
                yield InvestigationEvent(
                    type=evt.get("type", "status"),
                    name=evt.get("name"),
                    status=evt.get("status"),
                    text=evt.get("text"),
                )
        proc.wait()
        stderr = proc.stderr.read().strip() if proc.stderr else ""
        if proc.returncode != 0 or (not saw_event and stderr):
            detail = stderr or f"sdk-runner exited with code {proc.returncode}"
            yield InvestigationEvent(type="error", text=detail)


def get_investigator() -> Investigator:
    mode = os.environ.get("BALLAST_INVESTIGATOR", "engine").lower()
    if mode == "cursor":
        return CursorInvestigator()
    if mode == "mock":
        return MockInvestigator()
    return EngineInvestigator()
