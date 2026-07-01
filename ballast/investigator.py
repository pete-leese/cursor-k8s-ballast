"""The investigator seam: brief in, a validated RCA out.

Three implementations behind one idea:

- The deterministic ``engine`` (see ``ballast.engine.analyze``) is the default:
  it reads the live cluster and needs no LLM, so the demo is reliable.
- ``MockInvestigator`` replays a realistic RCA from a fixture, so the pipeline
  runs with no cluster and no Cursor call at all.
- ``CursorInvestigator`` shells out to a Node ``@cursor/sdk`` runner (the same
  pattern as cursor-causa), forwarding the agent's streamed events and validating
  the final RCA against the contract — the trust boundary.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from pydantic import ValidationError

from .brief import InvestigationBrief
from .contract import RCA, GeneratedBy

_ROOT = Path(__file__).resolve().parent.parent


class MockInvestigator:
    """Replays a canned-but-realistic RCA from a fixture."""

    def __init__(self, fixture_path: str | Path | None = None) -> None:
        self.fixture = Path(fixture_path or _ROOT / "fixtures" / "rca_payments.json")

    def rca(self, *, service: str, investigation_id: str) -> RCA:
        rca = RCA.model_validate_json(self.fixture.read_text())
        rca.generated_by = GeneratedBy.mock
        rca.investigation_id = investigation_id
        rca.service = service
        return rca


class CursorInvestigator:
    """Runs a real Cursor cloud agent via a Node sdk-runner and validates its RCA.

    The runner emits normalised JSONL on stdout, ending with a
    ``{"type":"rca","data":{...}}`` line. We validate the final RCA against the
    contract here — invalid output is rejected, never rendered as a real finding.
    """

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

    def investigate(self, brief: InvestigationBrief):
        env = {
            **os.environ,
            "CURSOR_TARGET_REPO": self.repo_url,
            "CURSOR_TARGET_REF": self.repo_ref,
            "CURSOR_MODEL": self.model,
        }
        schema = (_ROOT / "schema" / "rca.schema.json").read_text()
        proc = subprocess.Popen(
            ["node", "run.mjs"],
            cwd=self.runner_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
        )
        assert proc.stdin and proc.stdout
        proc.stdin.write(json.dumps({"prompt": brief.to_agent_prompt(schema)}))
        proc.stdin.close()
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
                    yield {"type": "error", "text": f"RCA failed contract validation: {exc}"}
                    continue
                rca.generated_by = GeneratedBy.cursor
                yield {"type": "rca", "rca": rca}
            else:
                yield evt
        proc.wait()
