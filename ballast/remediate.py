"""Post-RCA remediation: GitHub issue + Cursor Cloud Agent fix PR."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .contract import Action, RCA
from .store import STORE

_ROOT = Path(__file__).resolve().parent.parent
_MERGE_WATCH_INTERVAL = int(os.environ.get("BALLAST_MERGE_WATCH_INTERVAL", "20"))
_PR_OPEN_WATCH_INTERVAL = int(os.environ.get("BALLAST_PR_OPEN_WATCH_INTERVAL", "10"))
_ISSUE_RE = re.compile(
    r"https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<num>\d+)"
)
_PR_URL_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+")
_last_reconcile_at: dict[str, float] = {}
_RECONCILE_MIN_INTERVAL_S = 5.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _remediate_enabled() -> bool:
    return os.environ.get("BALLAST_AUTO_REMEDIATE", "0") == "1"


def should_auto_remediate(rca: RCA) -> bool:
    if not _remediate_enabled() or not os.environ.get("CURSOR_API_KEY"):
        return False
    return rca.recommended_action.action in (Action.forward_fix, Action.rollback)


def _run_cmd(
    args: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd or _ROOT,
        input=input_text,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )


def _gh_auth_error() -> str | None:
    """Return an error message if gh cannot call the GitHub API, else None.

    ``gh auth status`` alone is a weak signal: Cursor/agent shells often cannot
    read the macOS keyring even when the user's interactive terminal is fine.
    Prefer an API probe, and prefer GH_TOKEN/GITHUB_TOKEN when set.
    """
    if not shutil.which("gh"):
        return "gh CLI not found — install from https://cli.github.com"

    env = os.environ.copy()
    # Prefer github.com for this repo unless the caller set GH_HOST.
    env.setdefault("GH_HOST", "github.com")

    api = subprocess.run(
        ["gh", "api", "user", "-q", ".login"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if api.returncode == 0 and api.stdout.strip():
        return None

    status = subprocess.run(
        ["gh", "auth", "status", "-h", "github.com"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    detail = (status.stderr or status.stdout or api.stderr or "").strip()
    lower = detail.lower()
    if "keyring" in lower or "invalid" in lower or "forbidden" in lower:
        return (
            "gh cannot use the stored github.com token from this process "
            "(keyring/token invalid here). In your own terminal run: "
            "gh auth refresh -h github.com — or set GH_TOKEN in .env for the API"
        )
    if not os.environ.get("GH_TOKEN") and not os.environ.get("GITHUB_TOKEN"):
        return (
            "gh is not authenticated for github.com API calls. "
            "Run: gh auth refresh -h github.com — or set GH_TOKEN in .env"
        )
    return f"gh api user failed: {detail or 'unknown error'}"


def _discover_pr_for_issue(issue_url: str) -> tuple[str | None, str | None]:
    """Find a PR that cross-references ``issue_url``.

    Cursor ``autoCreatePR`` often opens the PR before/without surfacing
    ``RunResult.git.branches[].prUrl`` to the SDK waiter. The issue timeline
    still gets a ``cross-referenced`` event we can read via ``gh api``.
    """
    m = _ISSUE_RE.match((issue_url or "").strip())
    if not m or not shutil.which("gh"):
        return None, None
    owner, repo, num = m.group("owner"), m.group("repo"), m.group("num")
    env = os.environ.copy()
    env.setdefault("GH_HOST", "github.com")
    proc = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{owner}/{repo}/issues/{num}/timeline",
            "--paginate",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None, None
    try:
        events = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(events, list):
        return None, None

    for ev in reversed(events):
        if (ev or {}).get("event") != "cross-referenced":
            continue
        source = (ev.get("source") or {}).get("issue") or {}
        pr = source.get("pull_request") or {}
        html = source.get("html_url") or pr.get("html_url")
        if not html and isinstance(pr.get("url"), str):
            # api.github.com/repos/.../pulls/30 → html pull URL
            api_url = pr["url"]
            html = api_url.replace(
                "api.github.com/repos/", "github.com/"
            ).replace("/pulls/", "/pull/")
        if html and "/pull/" in html:
            return html, ev.get("created_at")
    return None, None


def _record_pr(
    investigation_id: str,
    pr_url: str,
    *,
    opened_at: str | None = None,
    agent_id: str | None = None,
) -> None:
    updates: dict = {
        "remediation_status": "complete",
        "remediation_pr_url": pr_url,
        "remediation_pr_opened_at": opened_at or _now(),
        "remediation_error": None,
    }
    if agent_id:
        updates["remediation_agent_id"] = agent_id
    STORE.update(investigation_id, **updates)
    _watch_pr_merge(investigation_id, pr_url)


def reconcile_remediation(investigation_id: str) -> bool:
    """Backfill ``remediation_pr_url`` from the GitHub issue timeline if missing.

    Returns True when a PR URL was newly attached (timeline / UI should refresh).
    """
    now = time.time()
    last = _last_reconcile_at.get(investigation_id, 0.0)
    if now - last < _RECONCILE_MIN_INTERVAL_S:
        return False
    _last_reconcile_at[investigation_id] = now

    record = STORE.get(investigation_id)
    if record is None or record.remediation_pr_url or not record.github_issue_url:
        return False
    if record.remediation_status not in (
        "complete",
        "launching_agent",
        "failed",
        "queued",
        "creating_issue",
        None,
    ):
        return False
    pr_url, opened_at = _discover_pr_for_issue(record.github_issue_url)
    if not pr_url:
        return False
    _record_pr(
        investigation_id,
        pr_url,
        opened_at=opened_at,
        agent_id=record.remediation_agent_id,
    )
    return True


def _watch_pr_open(
    investigation_id: str, issue_url: str, *, max_checks: int = 90
) -> None:
    """Poll the issue timeline until a linked PR appears (or give up)."""

    def _loop() -> None:
        for _ in range(max_checks):
            record = STORE.get(investigation_id)
            if record is None or record.remediation_pr_url:
                return
            pr_url, opened_at = _discover_pr_for_issue(issue_url)
            if pr_url:
                _record_pr(
                    investigation_id,
                    pr_url,
                    opened_at=opened_at,
                    agent_id=record.remediation_agent_id,
                )
                return
            time.sleep(_PR_OPEN_WATCH_INTERVAL)

    threading.Thread(target=_loop, daemon=True).start()


def run_remediation(investigation_id: str, rca: RCA) -> None:
    try:
        current = STORE.get(investigation_id)
        if current is None:
            return

        # Already have a PR for this investigation — do not open another.
        if current.remediation_pr_url:
            STORE.update(
                investigation_id,
                remediation_status="complete",
                remediation_error=None,
            )
            _watch_pr_merge(investigation_id, current.remediation_pr_url)
            return

        # Same alert episode already filed an issue/PR on a prior (or sibling) run.
        prior = STORE.find_remediation_for_episode(
            current.alertname, current.service, current.alert_fired_at
        )
        if (
            prior
            and prior.id != investigation_id
            and (prior.github_issue_url or prior.remediation_pr_url)
        ):
            updates: dict = {
                "github_issue_url": prior.github_issue_url,
                "remediation_issue_created_at": prior.remediation_issue_created_at
                or _now(),
                "remediation_pr_url": prior.remediation_pr_url,
                "remediation_pr_opened_at": prior.remediation_pr_opened_at,
                "remediation_pr_merged_at": prior.remediation_pr_merged_at,
                "remediation_agent_id": prior.remediation_agent_id,
                "remediation_status": "complete",
                "remediation_error": (
                    None
                    if prior.remediation_pr_url
                    else "Reused existing GitHub issue for this alert episode"
                ),
            }
            STORE.update(investigation_id, **updates)
            if prior.remediation_pr_url:
                _watch_pr_merge(investigation_id, prior.remediation_pr_url)
            elif prior.github_issue_url:
                _watch_pr_open(investigation_id, prior.github_issue_url)
            return

        # Issue already on this record — skip create; resume PR discovery / agent.
        issue_url: str | None = None
        if current.github_issue_url and not current.remediation_pr_url:
            issue_url = current.github_issue_url
            pr_url, opened_at = _discover_pr_for_issue(issue_url)
            if pr_url:
                _record_pr(
                    investigation_id,
                    pr_url,
                    opened_at=opened_at,
                    agent_id=current.remediation_agent_id,
                )
                return

        STORE.update(
            investigation_id,
            remediation_status="launching_agent" if issue_url else "creating_issue",
            remediation_queued_at=current.remediation_queued_at or _now(),
            remediation_error=None,
        )

        if err := _gh_auth_error():
            raise RuntimeError(err)

        rca_path = Path(f"/tmp/ballast-rca-{investigation_id}.json")
        rca_path.write_text(rca.model_dump_json(indent=2))

        if not issue_url:
            title = (
                f"INCIDENT: {rca.service} — {rca.summary[:120]}"
                if rca.summary
                else f"INCIDENT: {rca.service}"
            )
            body_proc = _run_cmd(["./scripts/format-rca-issue.sh", str(rca_path)])
            if body_proc.returncode != 0:
                raise RuntimeError(body_proc.stderr.strip() or "format-rca-issue failed")

            issue_proc = _run_cmd(
                ["gh", "issue", "create", "--title", title, "--body", body_proc.stdout],
            )
            if issue_proc.returncode != 0:
                raise RuntimeError(issue_proc.stderr.strip() or "gh issue create failed")

            issue_url = issue_proc.stdout.strip()
            if not issue_url.startswith("http"):
                raise RuntimeError(f"unexpected gh issue output: {issue_url!r}")

            STORE.update(
                investigation_id,
                github_issue_url=issue_url,
                remediation_issue_created_at=_now(),
                remediation_status="launching_agent",
            )
        else:
            STORE.update(investigation_id, remediation_status="launching_agent")

        if not os.environ.get("CURSOR_API_KEY"):
            STORE.update(
                investigation_id,
                remediation_status="complete",
                remediation_error="CURSOR_API_KEY not set — issue filed only",
            )
            return

        payload = json.dumps({"issue_url": issue_url, "rca": rca.model_dump()})
        sdk_dir = _ROOT / "sdk-runner"
        if not (sdk_dir / "node_modules" / "@cursor" / "sdk").exists():
            raise RuntimeError("sdk-runner not installed — run: task sdk:install")

        agent_proc = _run_cmd(
            ["node", "remediate.mjs"],
            cwd=sdk_dir,
            input_text=payload,
        )

        pr_url: str | None = None
        agent_id: str | None = None
        for line in agent_proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                # SDK / node may print non-JSON noise; salvage PR URLs.
                if not pr_url:
                    m = _PR_URL_RE.search(line)
                    if m:
                        pr_url = m.group(0)
                continue
            if evt.get("type") == "pr" and evt.get("url"):
                pr_url = evt["url"]
            if isinstance(evt.get("name"), str) and evt["name"].startswith("bc-"):
                agent_id = evt["name"]
            if evt.get("type") == "error":
                raise RuntimeError(evt.get("text") or "remediation agent failed")
            # Opportunistic: status text sometimes carries the PR URL.
            if not pr_url:
                for key in ("url", "text"):
                    val = evt.get(key)
                    if isinstance(val, str):
                        m = _PR_URL_RE.search(val)
                        if m:
                            pr_url = m.group(0)
                            break

        if agent_proc.returncode != 0:
            err = agent_proc.stderr.strip() or agent_proc.stdout.strip()
            raise RuntimeError(err or f"remediate.mjs exited {agent_proc.returncode}")

        if not pr_url:
            pr_url, opened_at = _discover_pr_for_issue(issue_url)
        else:
            opened_at = _now()

        if pr_url:
            _record_pr(
                investigation_id,
                pr_url,
                opened_at=opened_at,
                agent_id=agent_id,
            )
        else:
            STORE.update(
                investigation_id,
                remediation_status="complete",
                remediation_agent_id=agent_id,
                remediation_error=None,
            )
            # Agent finished; PR may still be propagating on the issue timeline.
            _watch_pr_open(investigation_id, issue_url)
    except Exception as exc:
        STORE.update(
            investigation_id,
            remediation_status="failed",
            remediation_error=str(exc),
        )
        # Even on agent failure, a PR may already exist — keep watching.
        record = STORE.get(investigation_id)
        if record and record.github_issue_url and not record.remediation_pr_url:
            _watch_pr_open(investigation_id, record.github_issue_url)


def spawn_remediation(investigation_id: str, rca: RCA) -> None:
    threading.Thread(
        target=run_remediation,
        args=(investigation_id, rca),
        daemon=True,
    ).start()


def _pr_merged_at(pr_url: str) -> str | None:
    """Check a PR's merge state via `gh`. Returns the merge timestamp, if merged."""
    if not shutil.which("gh"):
        return None
    proc = _run_cmd(["gh", "pr", "view", pr_url, "--json", "state,mergedAt"])
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if data.get("state") == "MERGED":
        return data.get("mergedAt") or _now()
    return None


def _watch_pr_merge(
    investigation_id: str, pr_url: str, *, max_checks: int = 180
) -> None:
    """Poll a forward-fix PR for merge status and stamp the timeline when merged.

    Runs on its own daemon thread — remediation PRs are opened but never
    auto-merged (see sdk-runner/remediate.mjs), so this is the only way the
    console learns a human merged the fix.
    """

    def _loop() -> None:
        for _ in range(max_checks):
            record = STORE.get(investigation_id)
            if record is None or record.remediation_pr_merged_at:
                return
            merged_at = _pr_merged_at(pr_url)
            if merged_at:
                STORE.update(investigation_id, remediation_pr_merged_at=merged_at)
                return
            time.sleep(_MERGE_WATCH_INTERVAL)

    threading.Thread(target=_loop, daemon=True).start()
