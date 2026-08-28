from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from coderking.runtime.state import Role, TaskStatus


@dataclass
class AgentEvent:
    type: str
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["payload"] = self.payload
        return data


def status_event(role: Role, status: TaskStatus) -> AgentEvent:
    return AgentEvent("agent_status", {"role": role.value, "status": status.value})


def tool_event(name: str, status: str, **extra: Any) -> AgentEvent:
    return AgentEvent("tool_call", {"tool": name, "status": status, **extra})


def file_event(path: str, action: str) -> AgentEvent:
    return AgentEvent("file_change", {"file": path, "action": action})


def plan_event(items: list[dict[str, Any]]) -> AgentEvent:
    return AgentEvent("plan_update", {"plan": items})


def terminal_event(text: str) -> AgentEvent:
    return AgentEvent("terminal", {"text": text})


def test_event(text: str) -> AgentEvent:
    return AgentEvent("test_result", {"text": text})


def sandbox_event(backend: str, status: str, **extra: Any) -> AgentEvent:
    return AgentEvent("sandbox_status", {"backend": backend, "status": status, **extra})


def approval_event(reason: str, tool: str, arguments: dict[str, Any]) -> AgentEvent:
    return AgentEvent(
        "approval_required",
        {"reason": reason, "tool": tool, "arguments": arguments},
    )


def policy_event(
    action: str,
    tool: str,
    reason: str,
    *,
    rule: str | None = None,
    arguments: dict[str, Any] | None = None,
) -> AgentEvent:
    return AgentEvent(
        "policy_decision",
        {
            "action": action,
            "tool": tool,
            "reason": reason,
            "rule": rule,
            "arguments": arguments or {},
        },
    )


def done_event(ok: bool, summary: str) -> AgentEvent:
    return AgentEvent("done", {"ok": ok, "summary": summary})


def error_event(message: str) -> AgentEvent:
    return AgentEvent("error", {"message": message})


def token_event(prompt: int, completion: int) -> AgentEvent:
    return AgentEvent("token_usage", {"prompt": prompt, "completion": completion})


def steer_event(content: str) -> AgentEvent:
    return AgentEvent("steer", {"content": content})


def follow_up_event(content: str) -> AgentEvent:
    return AgentEvent("follow_up", {"content": content})


def project_instructions_event(source: str, content_hash: str, *, truncated: bool) -> AgentEvent:
    return AgentEvent(
        "project_instructions",
        {"source": source, "hash": content_hash, "truncated": truncated},
    )


def skill_injected_event(name: str, *, truncated: bool) -> AgentEvent:
    return AgentEvent("skill_injected", {"name": name, "truncated": truncated})
