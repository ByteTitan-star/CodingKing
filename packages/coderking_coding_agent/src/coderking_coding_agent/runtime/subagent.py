"""Subagent tool + dynamic-workflow orchestration (Claude-Code-style).

The parent agent can spawn nested single-purpose agents with a restricted
tool surface and a fresh context; their final reply comes back as the tool
result. A ``plan`` tool lets the model maintain a working plan (TodoWrite
equivalent). Both tools only exist when ``RuntimeConfig.dynamic_workflow``
is enabled — the default four-atomic-tool surface is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from coderking_agent_core.cancel import CancelledRun
from coderking_agent_core.loop import (
    AgentLoopConfig,
    ToolCallRequest,
    TurnResult,
    run_agent_loop,
)
from coderking_agent_core.types import AgentContext
from coderking_coding_agent.runtime.events import AgentEvent, plan_event
from coderking_coding_agent.runtime.state import AgentState, PlanItem
from coderking_coding_agent.safety.policy import PolicyEngine
from coderking_coding_agent.sandbox.base import Sandbox
from coderking_coding_agent.tools.base import Tool, ToolResult

EXPLORE_PROMPT = """\
You are a read-only code investigation agent. You answer questions about the
repository by reading files and running non-mutating shell commands (grep,
find, ls, git log). You NEVER create, edit, or delete files — state your
findings with file paths and line references instead. When you have enough
evidence, reply with a concise, self-contained summary; the caller only sees
that final reply, not your tool activity.
"""

GENERAL_PROMPT = """\
You are a focused coding subagent. Complete the specific task you are given
autonomously with read/write/edit/bash: explore what you need, make the
change, verify it, then reply with a concise summary of what you changed and
the verification result. You cannot spawn further subagents. The caller only
sees your final reply, so it must be self-contained.
"""


class _SubagentSpec:
    def __init__(
        self,
        name: str,
        description: str,
        tool_names: tuple[str, ...],
        system_prompt: str,
    ):
        self.name = name
        self.description = description
        self.tool_names = tool_names
        self.system_prompt = system_prompt


SUBAGENT_TYPES: dict[str, _SubagentSpec] = {
    "general-purpose": _SubagentSpec(
        name="general-purpose",
        description=(
            "A general-purpose agent for complex, multi-step tasks. Full "
            "read/write/edit/bash access; returns a self-contained summary."
        ),
        tool_names=("read", "write", "edit", "bash", "shell", "run_tests", "git"),
        system_prompt=GENERAL_PROMPT,
    ),
    "explore": _SubagentSpec(
        name="explore",
        description=(
            "A read-only search agent for broad codebase sweeps — locating "
            "code, symbols, or conventions when you only need the conclusion."
        ),
        tool_names=("read", "bash", "shell"),
        system_prompt=EXPLORE_PROMPT,
    ),
}

DYNAMIC_WORKFLOW_PROMPT = """\

## Dynamic workflow orchestration

You can orchestrate work dynamically instead of doing everything yourself:

- Maintain a working plan with the `plan` tool: a short list of steps with
  status `pending` / `in_progress` / `done`. Update it as work progresses —
  one step `in_progress` at a time.
- Delegate self-contained subtasks to subagents with the `agent` tool. Each
  subagent starts with a fresh context and only sees the prompt you give it,
  so make that prompt self-contained (goal, constraints, relevant paths).
  Use `explore` for read-only investigation sweeps and `general-purpose`
  for multi-step changes.
- When subtasks are independent, emit several `agent` calls in the same turn
  so they run in parallel; otherwise finish one before starting the next.
- Subagents cannot spawn subagents. Keep the plan at your level, delegate
  the leaves.
- After subagents finish, verify their claims (run tests, read the diffs)
  before declaring the overall task complete.
"""


def make_plan_tool(state: AgentState, on_event: Any) -> Tool:
    """TodoWrite-equivalent: the model maintains the working plan."""

    class PlanTool(Tool):
        name = "plan"
        description = (
            "Update the working plan shown to the user. Provide the full list "
            "of steps; each has a title and status (pending|in_progress|done). "
            "Keep exactly one step in_progress."
        )
        parameters = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "done"],
                            },
                        },
                        "required": ["title", "status"],
                    },
                }
            },
            "required": ["items"],
        }

        async def execute(self, **kwargs: Any) -> ToolResult:
            raw = kwargs.get("items")
            if not isinstance(raw, list) or not raw:
                return ToolResult(False, "plan requires a non-empty items list")
            if len(raw) > 20:
                return ToolResult(False, "plan is limited to 20 items")
            statuses = {"pending", "in_progress", "done"}
            plan: list[PlanItem] = []
            for item in raw:
                if not isinstance(item, dict):
                    return ToolResult(False, "each plan item must be an object")
                title = str(item.get("title") or "").strip()
                status = str(item.get("status") or "pending")
                if not title:
                    return ToolResult(False, "each plan item needs a title")
                if status not in statuses:
                    return ToolResult(
                        False,
                        f"invalid status {status!r}: use pending|in_progress|done",
                    )
                plan.append(PlanItem(title=title, done=status == "done"))
            state.plan = plan
            payload = [
                {
                    "title": item.title,
                    "done": item.done,
                    "status": "done" if item.done else "pending",
                }
                for item in plan
            ]
            # mark the first open step as in_progress for the UI
            for entry in payload:
                if not entry["done"]:
                    entry["status"] = "in_progress"
                    break
            await on_event(plan_event(payload))
            done = sum(1 for item in plan if item.done)
            return ToolResult(True, f"plan updated: {done}/{len(plan)} done")

    return PlanTool()


def make_subagent_tool(
    *,
    llm: Any,
    tools_pool: dict[str, Tool],
    workspace: Path,
    source: Path,
    sandbox: Sandbox,
    policy_engine: PolicyEngine,
    checkpoint_store: Any | None,
    parent_state: AgentState,
    approve: Any | None,
    auto_approve: bool,
    cancel: Any | None,
    max_turns: int,
    on_event: Any,
) -> Tool:
    """Build the `agent` tool that spawns nested single-purpose agents."""

    class SubagentTool(Tool):
        name = "agent"
        description = (
            "Spawn a subagent for a self-contained subtask and wait for its "
            "final reply (returned as the tool result). The subagent starts "
            "with a fresh context and only sees the prompt you pass — include "
            "goal, constraints and relevant paths. agent_type: "
            "'general-purpose' (full coding tools) or 'explore' (read-only)."
        )
        parameters = {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "3-5 word summary of the subtask",
                },
                "prompt": {
                    "type": "string",
                    "description": "Complete, self-contained task for the subagent",
                },
                "agent_type": {
                    "type": "string",
                    "enum": ["general-purpose", "explore"],
                },
            },
            "required": ["description", "prompt"],
        }

        async def execute(self, **kwargs: Any) -> ToolResult:
            # imported lazily: these live in atomic_l1, which imports this module
            from coderking_coding_agent.runtime.atomic_l1 import (
                agent_message_from_dict,
                openai_messages_from_context,
                tool_schemas,
                wrap_phase1_tool,
            )

            description = str(kwargs.get("description") or "").strip()[:80]
            prompt = str(kwargs.get("prompt") or "").strip()
            agent_type = str(kwargs.get("agent_type") or "general-purpose")
            spec = SUBAGENT_TYPES.get(agent_type)
            if spec is None:
                return ToolResult(
                    False,
                    f"unknown agent_type {agent_type!r}: use {'/'.join(SUBAGENT_TYPES)}",
                )
            if not prompt:
                return ToolResult(False, "prompt is required")
            if not description:
                description = f"{agent_type} subtask"

            available = {name: tools_pool[name] for name in spec.tool_names if name in tools_pool}

            async def emit_marked(event: AgentEvent) -> None:
                # policy/checkpoint/approval events from wrapped tools reach
                # the parent stream with a subagent marker so the UI can
                # label them (and approvals still surface for HITL)
                await on_event(AgentEvent(event.type, {**event.payload, "subagent": description}))

            # writes inside a subagent surface in the parent's state
            # (changed_files / checkpoints) so accept/rollback stays coherent
            sub_tools = [
                wrap_phase1_tool(
                    tool,
                    policy_engine=policy_engine,
                    on_event=emit_marked,
                    source=source,  # policy patterns match the real repo root
                    state=parent_state,
                    approve=approve,
                    auto_approve=auto_approve,
                    persist=None,  # subagent runs never persist task state
                    checkpoint_store=checkpoint_store,
                )
                for tool in available.values()
            ]
            context = AgentContext(
                system_prompt=spec.system_prompt,
                tools=sub_tools,
                messages=[
                    agent_message_from_dict(m)
                    for m in (
                        {"role": "system", "content": spec.system_prompt},
                        {"role": "user", "content": prompt},
                    )
                ],
            )

            async def complete_turn(ctx: AgentContext) -> TurnResult:
                if cancel is not None and getattr(cancel, "cancelled", False):
                    raise CancelledRun("subagent cancelled")
                messages = openai_messages_from_context(ctx)
                schemas = tool_schemas(ctx.tools)
                complete = llm.complete

                async def on_delta(_text: str) -> None:  # noqa: ARG001
                    return None  # keep subagent streaming out of the parent transcript

                try:
                    response = await complete(messages, schemas, cancel=cancel, on_delta=on_delta)
                except TypeError:
                    try:
                        response = await complete(messages, schemas, cancel=cancel)
                    except TypeError:
                        response = await complete(messages, schemas)
                parent_state.token_input += response.prompt_tokens
                parent_state.token_output += response.completion_tokens
                calls = [
                    ToolCallRequest(id=c.id, name=c.name, arguments=c.arguments)
                    for c in response.tool_calls
                ]
                return TurnResult(
                    content=response.content,
                    tool_calls=calls,
                    stop_reason="tool_use" if calls else "end_turn",
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                )

            calls_seen = 0

            async def emit(event: dict[str, Any]) -> None:
                # bridge the loop's dict events into parent-stream tool_call
                # events (the parent run does the same via _bridge_l1_event)
                nonlocal calls_seen
                kind = str(event.get("type") or "")
                if kind == "tool_execution_start":
                    await on_event(
                        AgentEvent(
                            "tool_call",
                            {
                                "tool": str(event.get("name") or ""),
                                "status": "running",
                                "arguments": event.get("arguments")
                                if isinstance(event.get("arguments"), dict)
                                else {},
                                "subagent": description,
                            },
                        )
                    )
                elif kind == "tool_execution_end":
                    calls_seen += 1
                    await on_event(
                        AgentEvent(
                            "tool_call",
                            {
                                "tool": str(event.get("name") or ""),
                                "status": "ok" if event.get("ok") else "error",
                                "preview": str(event.get("output") or "")[:500],
                                "subagent": description,
                            },
                        )
                    )
                elif kind == "error":
                    await emit_marked(
                        AgentEvent("error", {"message": str(event.get("message") or "error")})
                    )

            await on_event(
                AgentEvent(
                    "subagent_start",
                    {
                        "description": description,
                        "agent_type": agent_type,
                        "prompt": prompt[:500],
                    },
                )
            )
            ok = True
            error = ""
            summary = ""
            try:
                final = await run_agent_loop(
                    context,
                    AgentLoopConfig(
                        complete_turn=complete_turn,
                        max_turns=max_turns,
                        tool_execution="sequential",
                    ),
                    emit,
                )
                for message in reversed(final.messages):
                    if getattr(message, "role", "") == "assistant":
                        content = getattr(message, "content", "")
                        if isinstance(content, str) and content.strip():
                            summary = content.strip()
                            break
                summary = summary or "(subagent finished without a text reply)"
            except Exception as exc:  # noqa: BLE001
                ok = False
                error = f"{type(exc).__name__}: {exc}"
            await on_event(
                AgentEvent(
                    "subagent_end",
                    {
                        "description": description,
                        "agent_type": agent_type,
                        "ok": ok,
                        "summary": (summary if ok else error)[:500],
                        "tool_calls": calls_seen,
                    },
                )
            )
            text = (
                f"[subagent:{agent_type} · {description}]\n{summary}"
                if ok
                else f"[subagent:{agent_type} · {description} failed]\n{error}"
            )
            return ToolResult(ok, text)

    return SubagentTool()
