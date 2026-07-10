"""RCA discussion chat via Cursor Cloud Agents API (follow-up runs)."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

import httpx

from .store import InvestigationRecord

CHAT_SYSTEM = """You are Ballast, an incident response copilot helping an engineer
walk through a completed root-cause analysis for a Kubernetes/GitOps incident.

Rules:
- Ground every answer in the RCA, investigation brief, and any live cluster
  context provided below.
- Be concise but thorough. Use bullet points for multi-part answers.
- When asked to dig deeper, cite specific evidence rows, telemetry signals, or
  timeline events from the RCA.
- If the user asks about remediation, reference recommended_action and blast radius.
- Do not invent cluster facts not present in the context. If data is missing, say so.
- This is a read-only discussion — do not modify the repo or claim to have merged a PR.
"""

_TERMINAL = frozenset({"FINISHED", "ERROR", "CANCELLED", "EXPIRED"})


def _cursor_base() -> str:
    return os.environ.get("CURSOR_API_BASE", "https://api.cursor.com").rstrip("/")


def _cursor_auth() -> tuple[str, str]:
    api_key = os.environ.get("CURSOR_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "CURSOR_API_KEY not set — add it to .env and restart the Ballast API."
        )
    return api_key, ""


def chat_available() -> bool:
    return bool(os.environ.get("CURSOR_API_KEY"))


def resolve_investigation_agent(record: InvestigationRecord) -> str | None:
    """Return the Cursor cloud agent that ran the investigation, if any."""
    if record.cursor_agent_id:
        return record.cursor_agent_id
    for event in record.events:
        if event.name and str(event.name).startswith("bc-"):
            return event.name
    return None


def build_chat_context(
    record: InvestigationRecord,
    *,
    argocd: dict[str, Any] | None = None,
    kube: dict[str, Any] | None = None,
) -> str:
    parts: list[str] = []
    if record.rca is not None:
        parts.append(
            "## Root cause analysis (authoritative)\n"
            + record.rca.model_dump_json(indent=2)
        )
    if record.brief is not None:
        parts.append(
            "## Investigation brief (triage)\n" + record.brief.model_dump_json(indent=2)
        )
    if argocd:
        parts.append("## Live ArgoCD state\n" + json.dumps(argocd, indent=2))
    if kube:
        parts.append("## Live Kubernetes state\n" + json.dumps(kube, indent=2))
    parts.append(f"## Investigation id\n{record.id}")
    return "\n\n".join(parts)


def _build_prompt(
    record: InvestigationRecord,
    user_message: str,
    *,
    argocd: dict[str, Any] | None = None,
    kube: dict[str, Any] | None = None,
) -> str:
    context = build_chat_context(record, argocd=argocd, kube=kube)
    prior_lines: list[str] = []
    for msg in record.chat_messages[:-1]:
        role = "Engineer" if msg.role == "user" else "Ballast"
        prior_lines.append(f"{role}: {msg.content}")

    parts = [CHAT_SYSTEM, context]
    if prior_lines:
        parts.append("## Prior discussion in Ballast console\n" + "\n".join(prior_lines))
    parts.append(f"## Engineer question\n{user_message}")
    return "\n\n".join(parts)


def _wait_for_run(
    client: httpx.Client,
    agent_id: str,
    run_id: str,
    *,
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = client.get(f"/v1/agents/{agent_id}/runs/{run_id}")
        if resp.status_code >= 400:
            raise RuntimeError(f"Cursor run poll failed {resp.status_code}: {resp.text[:400]}")
        data = resp.json()
        if data.get("status") in _TERMINAL:
            return data
        time.sleep(2.5)
    raise RuntimeError("Cursor agent run timed out — check cursor.com/agents")


def _extract_result(run_data: dict[str, Any]) -> str:
    status = run_data.get("status")
    if status == "ERROR":
        raise RuntimeError(run_data.get("result") or "Cursor agent run failed")
    text = (run_data.get("result") or "").strip()
    if not text:
        raise RuntimeError("Cursor agent returned an empty reply")
    return text


def _create_discuss_agent(
    client: httpx.Client,
    record: InvestigationRecord,
    prompt_text: str,
) -> tuple[str, str]:
    """Create a cloud agent for RCA discussion (engine/mock investigations)."""
    repo_url = os.environ.get(
        "CURSOR_TARGET_REPO", "https://github.com/pete-leese/cursor-k8s-ballast"
    )
    repo_ref = os.environ.get("CURSOR_TARGET_REF", "main")
    # Must be a currently valid Cloud Agents model id (composer-2 is rejected).
    model_id = os.environ.get("CURSOR_MODEL", "composer-2.5")

    payload: dict[str, Any] = {
        "prompt": {"text": prompt_text},
        "repos": [{"url": repo_url, "startingRef": repo_ref}],
        "autoCreatePR": False,
        "name": f"Ballast RCA discuss · {record.service}",
        "model": {"id": model_id},
    }
    resp = client.post("/v1/agents", json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Cursor agent create failed {resp.status_code}: {resp.text[:400]}"
        )
    body = resp.json()
    agent_id = body.get("agent", {}).get("id") or body.get("id")
    run_id = body.get("run", {}).get("id")
    if not agent_id or not run_id:
        raise RuntimeError(f"Unexpected Cursor create response: {body}")
    return agent_id, run_id


def _post_followup(
    client: httpx.Client,
    agent_id: str,
    prompt_text: str,
) -> str:
    resp = client.post(
        f"/v1/agents/{agent_id}/runs",
        json={"prompt": {"text": prompt_text}},
    )
    if resp.status_code == 409:
        raise RuntimeError(
            "Cursor agent is busy — wait for the prior run to finish, then retry."
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Cursor follow-up failed {resp.status_code}: {resp.text[:400]}")
    run_id = resp.json().get("run", {}).get("id")
    if not run_id:
        raise RuntimeError(f"Unexpected Cursor follow-up response: {resp.text[:400]}")
    return run_id


def reply(
    record: InvestigationRecord,
    user_message: str,
    *,
    argocd: dict[str, Any] | None = None,
    kube: dict[str, Any] | None = None,
    on_chat_agent_created: Callable[[str], None] | None = None,
) -> str:
    """Send a follow-up via Cursor Cloud Agents API."""
    if record.rca is None:
        raise ValueError("RCA not available yet")

    prompt = _build_prompt(record, user_message, argocd=argocd, kube=kube)
    auth = _cursor_auth()
    base = _cursor_base()

    with httpx.Client(base_url=base, auth=auth, timeout=30.0) as client:
        inv_agent = resolve_investigation_agent(record)
        chat_agent = record.chat_agent_id

        if inv_agent:
            run_id = _post_followup(client, inv_agent, prompt)
            run_data = _wait_for_run(client, inv_agent, run_id)
            return _extract_result(run_data)

        if chat_agent:
            run_id = _post_followup(client, chat_agent, prompt)
            run_data = _wait_for_run(client, chat_agent, run_id)
            return _extract_result(run_data)

        agent_id, run_id = _create_discuss_agent(client, record, prompt)
        if on_chat_agent_created:
            on_chat_agent_created(agent_id)
        run_data = _wait_for_run(client, agent_id, run_id)
        return _extract_result(run_data)
