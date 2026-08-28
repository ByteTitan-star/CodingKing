"""Map agent event records to TUI panel lines."""

from __future__ import annotations

from typing import Any, Literal

PanelName = Literal["chat", "tools", "terminal", "status"]


def format_agent_event(record: dict[str, Any]) -> tuple[PanelName, str] | None:
    event_type = str(record.get("type") or "")
    payload = record.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    if event_type == "agent_status":
        role = payload.get("role", "?")
        status = payload.get("status", "?")
        return "status", f"role={role} status={status}"

    if event_type == "phase_change":
        phase = payload.get("phase", "?")
        previous = payload.get("from")
        if previous:
            return "status", f"phase {previous} → {phase}"
        return "status", f"phase={phase}"

    if event_type == "tool_call":
        tool = payload.get("tool", "?")
        status = payload.get("status", "?")
        return "tools", f"{tool} [{status}]"

    if event_type == "policy_decision":
        action = payload.get("action", "?")
        tool = payload.get("tool", "?")
        return "tools", f"policy {action} on {tool}"

    if event_type == "terminal":
        text = str(payload.get("text") or "").strip()
        return ("terminal", text) if text else None

    if event_type == "test_result":
        text = str(payload.get("text") or "").strip()
        return ("terminal", f"[test] {text}") if text else None

    if event_type == "plan_update":
        plan = payload.get("plan") or []
        if not isinstance(plan, list):
            return None
        lines = [
            f"{'✓' if item.get('done') else '○'} {item.get('title', '')}"
            for item in plan
            if isinstance(item, dict)
        ]
        return ("chat", "plan:\n" + "\n".join(lines)) if lines else None

    if event_type == "token_usage":
        prompt = payload.get("prompt", 0)
        completion = payload.get("completion", 0)
        return "status", f"tokens in={prompt} out={completion}"

    if event_type == "approval_required":
        tool = payload.get("tool", "?")
        reason = payload.get("reason", "")
        return "chat", f"[approval] {tool}: {reason}"

    if event_type == "done":
        ok = payload.get("ok")
        summary = str(payload.get("summary") or "").strip()
        head = f"[done ok={ok}]"
        return ("chat", f"{head}\n{summary}" if summary else head)

    if event_type == "error":
        return "chat", f"[error] {payload.get('message', '')}"

    if event_type in {"steer", "follow_up"}:
        content = str(payload.get("content") or "")
        return "chat", f"[{event_type}] {content}"

    if event_type == "file_change":
        path = payload.get("file", "?")
        action = payload.get("action", "?")
        return "tools", f"file {action}: {path}"

    return None
