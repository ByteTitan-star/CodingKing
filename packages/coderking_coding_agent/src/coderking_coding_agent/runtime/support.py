"""Shared runtime helpers for the pure coding-agent loop (no role workflow)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from coderking_coding_agent.runtime.events import (
    AgentEvent,
    follow_up_event,
    status_event,
    steer_event,
)
from coderking_coding_agent.runtime.queues import RunMessageQueues
from coderking_coding_agent.runtime.state import AgentState, TaskStatus
from coderking_coding_agent.safety.policy import PolicyDecision

EventSink = Callable[[AgentEvent], Awaitable[None]]
ApprovalFn = Callable[[str, str, dict[str, Any]], Awaitable[bool]]


async def inject_steering_messages(
    state: AgentState,
    items: list[str],
    on_event: EventSink,
) -> None:
    for text in items:
        state.messages.append({"role": "user", "content": f"[steer] {text}"})
        await on_event(steer_event(text))


async def inject_steering(
    state: AgentState,
    queues: RunMessageQueues,
    on_event: EventSink,
) -> None:
    items = await queues.drain_steering()
    if items:
        await inject_steering_messages(state, items, on_event)


async def inject_follow_up(
    state: AgentState,
    queues: RunMessageQueues,
    on_event: EventSink,
) -> bool:
    items = await queues.drain_follow_up()
    if not items:
        return False
    for text in items:
        state.messages.append({"role": "user", "content": f"[follow-up] {text}"})
        await on_event(follow_up_event(text))
    state.status = TaskStatus.RUNNING
    await on_event(status_event(state.role, state.status))
    return True


def audit_policy_decision(
    workspace: Path,
    tool_name: str,
    arguments: dict[str, Any],
    decision: PolicyDecision,
) -> None:
    if decision.action.value == "allow":
        return
    try:
        from coderking_coding_agent.sandbox.credentials import redact_tool_arguments
        from coderking_coding_agent.session.repo import SessionRepo

        repo = SessionRepo(workspace, session_id="policy-audit")
        repo.append(
            "audit",
            {
                "tool": tool_name,
                "arguments": redact_tool_arguments(arguments),
                "decision": decision.to_dict(),
            },
        )
    except OSError:
        return


# Compatibility aliases used by older imports/tests.
_inject_steering_messages = inject_steering_messages
_inject_steering = inject_steering
_inject_follow_up = inject_follow_up
_audit_policy_decision = audit_policy_decision
