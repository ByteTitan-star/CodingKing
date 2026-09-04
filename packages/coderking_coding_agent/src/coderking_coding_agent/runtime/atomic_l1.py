"""Atomic tool profile driven by L1 ``run_agent_loop`` (Pi-style)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from coderking_agent_core.cancel import CancelledRun, RunCancel
from coderking_agent_core.loop import (
    AgentLoopConfig,
    ToolCallRequest,
    TurnResult,
    run_agent_loop,
)
from coderking_agent_core.types import AgentContext, AgentMessage, AgentTool
from coderking_coding_agent.context.project_docs import inject_project_instructions
from coderking_coding_agent.context.skills import SkillRegistry, inject_matching_skills
from coderking_coding_agent.runtime.config import RuntimeBindings, RuntimeConfig
from coderking_coding_agent.runtime.events import (
    AgentEvent,
    approval_event,
    done_event,
    error_event,
    phase_change_event,
    policy_event,
    project_instructions_event,
    sandbox_event,
    skill_injected_event,
    status_event,
    token_event,
    tool_event,
)
from coderking_coding_agent.runtime.queues import RunMessageQueues
from coderking_coding_agent.runtime.state import AgentState, Role, TaskStatus, ToolRecord
from coderking_coding_agent.runtime.support import audit_policy_decision
from coderking_coding_agent.safety.policy import PolicyAction, PolicyEngine
from coderking_coding_agent.sandbox.cow import CowWorkspace
from coderking_coding_agent.tools.base import Tool
from coderking_llm.provider import LLMProvider

EventSink = Callable[[AgentEvent], Awaitable[None]]
ApprovalFn = Callable[[str, str, dict[str, Any]], Awaitable[bool]]


def wrap_phase1_tool(
    tool: Tool,
    *,
    policy_engine: PolicyEngine,
    on_event: EventSink,
    source: Path,
    state: AgentState,
    approve: ApprovalFn | None,
    auto_approve: bool,
) -> AgentTool:
    schema = tool.schema()
    fn = schema.get("function") or {}
    parameters = fn.get("parameters") or tool.parameters

    async def execute(**kwargs: Any) -> tuple[bool, str]:
        legacy_approval = bool(getattr(tool, "requires_approval", False))
        decision = policy_engine.evaluate(
            tool.name,
            kwargs,
            legacy_requires_approval=legacy_approval,
        )
        await on_event(
            policy_event(
                decision.action.value,
                tool.name,
                decision.reason,
                rule=decision.rule,
                arguments=kwargs,
            )
        )
        audit_policy_decision(source, tool.name, kwargs, decision)
        if decision.action == PolicyAction.DENY:
            return False, f"policy denied: {decision.reason}"
        if decision.action == PolicyAction.ASK and not auto_approve:
            state.status = TaskStatus.WAITING_APPROVAL
            await on_event(approval_event(decision.reason, tool.name, kwargs))
            allowed = False
            if approve is not None:
                allowed = await approve(tool.name, decision.reason, kwargs)
            state.status = TaskStatus.RUNNING
            if not allowed:
                return False, "user rejected the operation"
        result = await tool.execute(**kwargs)
        return bool(result.ok), str(result.output)

    return AgentTool(
        name=tool.name,
        description=str(fn.get("description") or tool.description),
        parameters=parameters if isinstance(parameters, dict) else {},
        execute=execute,
    )


def openai_messages_from_context(ctx: AgentContext) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": ctx.system_prompt}]
    for msg in ctx.messages:
        if msg.role == "tool":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id or "",
                    "content": msg.content or "",
                }
            )
            continue
        item: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_calls:
            item["tool_calls"] = msg.tool_calls
            item["content"] = msg.content
        messages.append(item)
    return messages


def tool_schemas(tools: list[AgentTool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]


class AtomicL1Runtime:
    """Pi-style atomic agent: L1 loop + read/write/edit/bash only."""

    def __init__(
        self,
        config: RuntimeConfig,
        llm: LLMProvider,
        bindings: RuntimeBindings,
        *,
        system_prompt: str,
        cancel: Any | None = None,
    ) -> None:
        self.config = config
        self.llm = llm
        self.bindings = bindings
        self.system_prompt = system_prompt
        self.cancel = cancel
        self._run_cancel = RunCancel()

    async def run(
        self,
        prompt: str,
        workspace: Path,
        *,
        on_event: EventSink,
        queues: RunMessageQueues | None = None,
        state: AgentState | None = None,
        approve: ApprovalFn | None = None,
        auto_approve: bool = False,
    ) -> AgentState:
        workspace = workspace.resolve()
        source = workspace
        state = state or AgentState(task=prompt, repository=str(source))
        state.status = TaskStatus.RUNNING
        state.role = Role.CODING
        cow: CowWorkspace | None = None
        if self.config.sandbox_cow:
            cow = CowWorkspace(source, session_id=state.task_id)
            workspace = cow.materialize()

        sandbox, note = await self.bindings.create_sandbox(workspace, cow)
        if self.cancel is not None:
            sandbox.cancel = self.cancel  # type: ignore[attr-defined]
        state.sandbox_backend = sandbox.name
        state.sandbox_status = "active"
        await on_event(sandbox_event(sandbox.name, "active", note=note))
        await on_event(status_event(state.role, state.status))

        policy_engine = PolicyEngine.load(source)
        phase1_tools = dict(self.bindings.build_tools(workspace, sandbox))
        agent_tools = [
            wrap_phase1_tool(
                tool,
                policy_engine=policy_engine,
                on_event=on_event,
                source=source,
                state=state,
                approve=approve,
                auto_approve=auto_approve,
            )
            for tool in phase1_tools.values()
        ]
        context = AgentContext(system_prompt=self.system_prompt, tools=agent_tools)

        # Pi-style progressive disclosure: AGENTS.md + matching skills on first turn only.
        seed: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        if not state.messages:
            seed, project_doc = inject_project_instructions(source, seed)
            if project_doc is not None:
                await on_event(
                    project_instructions_event(
                        project_doc.source,
                        project_doc.content_hash,
                        truncated=project_doc.truncated,
                    )
                )
            skill_registry = SkillRegistry(source, include_cursor=False)
            seed, injected_skills = inject_matching_skills(
                source,
                seed,
                prompt,
                registry=skill_registry,
            )
            for skill in injected_skills:
                await on_event(
                    skill_injected_event(skill.manifest.name, truncated=skill.truncated)
                )
        initial_messages = [
            AgentMessage(role=str(m["role"]), content=str(m.get("content") or ""))
            for m in seed
            if m.get("role") != "system"
        ]

        async def complete_turn(ctx: AgentContext) -> TurnResult:
            if self.cancel is not None and getattr(self.cancel, "cancelled", False):
                self._run_cancel.abort()
                raise CancelledRun("cancelled")
            self._run_cancel.raise_if_aborted()
            messages = openai_messages_from_context(ctx)
            schemas = tool_schemas(ctx.tools)
            complete = self.llm.complete
            try:
                response = await complete(messages, schemas, cancel=self.cancel)
            except TypeError:
                response = await complete(messages, schemas)
            state.token_input += response.prompt_tokens
            state.token_output += response.completion_tokens
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

        async def get_steering() -> list[AgentMessage]:
            if queues is None:
                return []
            items = await queues.drain_steering()
            return [AgentMessage(role="user", content=f"[steer] {text}") for text in items]

        async def get_follow_up() -> list[AgentMessage]:
            if queues is None:
                return []
            items = await queues.drain_follow_up()
            return [AgentMessage(role="user", content=f"[follow-up] {text}") for text in items]

        async def should_stop(ctx: AgentContext, turn: TurnResult, _results: list) -> bool:
            return not turn.tool_calls

        async def emit(event: dict[str, Any]) -> None:
            await _bridge_l1_event(event, on_event, state, pending_args)

        pending_args: dict[str, dict[str, Any]] = {}
        try:
            final = await run_agent_loop(
                context,
                AgentLoopConfig(
                    complete_turn=complete_turn,
                    get_steering_messages=get_steering,
                    get_follow_up_messages=get_follow_up,
                    should_stop_after_turn=should_stop,
                    max_turns=self.config.max_iterations,
                    tool_execution="sequential",
                    cancel=self._run_cancel,
                ),
                emit,
                initial_messages=initial_messages,
            )
            state.messages = [
                {"role": "system", "content": self.system_prompt},
                *[
                    {
                        "role": m.role,
                        "content": m.content,
                        **({"tool_calls": m.tool_calls} if m.tool_calls else {}),
                        **({"tool_call_id": m.tool_call_id} if m.tool_call_id else {}),
                    }
                    for m in final.messages
                ],
            ]
            if state.status == TaskStatus.RUNNING:
                state.status = TaskStatus.SUCCEEDED
                await on_event(done_event(True, "atomic agent completed"))
        except (CancelledRun, Exception) as exc:
            if isinstance(exc, CancelledRun) or (
                self.cancel is not None and getattr(self.cancel, "cancelled", False)
            ):
                state.status = TaskStatus.INTERRUPTED
                await on_event(done_event(False, "interrupted"))
            else:
                state.status = TaskStatus.FAILED
                state.errors.append(str(exc))
                await on_event(error_event(str(exc)))
                await on_event(done_event(False, str(exc)))
        finally:
            await sandbox.close()
            state.sandbox_status = "idle"
            if cow is not None:
                if state.status == TaskStatus.SUCCEEDED:
                    cow.promote()
                cow.close()
            self.bindings.persist_state(source, state)
        return state


async def _bridge_l1_event(
    event: dict[str, Any],
    on_event: EventSink,
    state: AgentState,
    pending_args: dict[str, dict[str, Any]],
) -> None:
    kind = str(event.get("type") or "")
    if kind == "phase_change":
        await on_event(
            phase_change_event(
                phase=str(event.get("phase") or ""),
                from_phase=str(event["from"]) if event.get("from") else None,
            )
        )
        return
    if kind == "token_usage":
        await on_event(
            token_event(int(event.get("prompt") or 0), int(event.get("completion") or 0))
        )
        return
    if kind == "tool_execution_start":
        call_id = str(event.get("tool_call_id") or "")
        args = event.get("arguments") if isinstance(event.get("arguments"), dict) else {}
        pending_args[call_id] = dict(args)
        await on_event(
            tool_event(
                str(event.get("name") or ""),
                "running",
                arguments=args,
            )
        )
        return
    if kind == "tool_execution_end":
        ok = bool(event.get("ok"))
        name = str(event.get("name") or "")
        call_id = str(event.get("tool_call_id") or "")
        preview = str(event.get("output") or "")[:500]
        arguments = pending_args.pop(call_id, {})
        await on_event(tool_event(name, "ok" if ok else "error", preview=preview))
        state.tool_history.append(ToolRecord(name=name, arguments=arguments, output=preview, ok=ok))
        return
    if kind == "error":
        await on_event(error_event(str(event.get("message") or "error")))
