from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from coderking.config import Settings
from coderking.diffing import snapshot_workspace, unified_diff
from coderking.llm.provider import LLMProvider, LLMResponse, ToolCall
from coderking.mcp.host import McpHost
from coderking.memory.store import MemoryStore
from coderking.prompts.loader import resolve_system_prompt
from coderking.registry import cancel_requested, persist_state
from coderking.runtime.cancel import CancellationToken, CancelledTask
from coderking.runtime.events import (
    AgentEvent,
    approval_event,
    done_event,
    error_event,
    file_event,
    follow_up_event,
    phase_change_event,
    plan_event,
    policy_event,
    project_instructions_event,
    sandbox_event,
    skill_injected_event,
    status_event,
    steer_event,
    terminal_event,
    test_event,
    token_event,
    tool_event,
)
from coderking.runtime.queues import RunMessageQueues
from coderking.runtime.roles import ROLE_TOOLS
from coderking.runtime.state import AgentState, PlanItem, Role, TaskStatus, ToolRecord
from coderking.sandbox.cow import CowWorkspace
from coderking.sandbox.manager import create_sandbox
from coderking.tools.dynamic_adapter import wrap_dynamic_tools
from coderking.tools.dynamic_runner import SandboxToolRunner
from coderking.tools.registry import build_tools
from coderking_agent_core.fsm import LoopEvent, PhaseFSM
from coderking_agent_core.types import LoopPhase
from coderking_coding_agent.context.project_docs import inject_project_instructions
from coderking_coding_agent.context.skills import SkillRegistry, inject_matching_skills
from coderking_coding_agent.safety.policy import PolicyAction, PolicyDecision, PolicyEngine
from coderking_coding_agent.tools.dynamic import DynamicToolLoader

EventSink = Callable[[AgentEvent], Awaitable[None]]
ApprovalFn = Callable[[str, str, dict[str, Any]], Awaitable[bool]]


class AgentRuntime:
    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        *,
        memory: MemoryStore | None = None,
        cancel: CancellationToken | None = None,
    ):
        self.settings = settings
        self.llm = llm
        self.memory = memory
        self.cancel = cancel or CancellationToken()
        self._run_queues: RunMessageQueues | None = None

    async def run(
        self,
        prompt: str,
        workspace: Path,
        *,
        on_event: EventSink,
        approve: ApprovalFn | None = None,
        auto_approve: bool = False,
        test_command: str | None = None,
        state: AgentState | None = None,
        queues: RunMessageQueues | None = None,
    ) -> AgentState:
        workspace = workspace.resolve()
        source = workspace
        state = state or AgentState(task=prompt, repository=str(source))
        self._run_queues = queues
        cow: CowWorkspace | None = None
        if self.settings.sandbox_cow:
            cow = CowWorkspace(source, session_id=state.task_id)
            workspace = cow.materialize()
        if not state.snapshot:
            state.snapshot = snapshot_workspace(workspace)
        state.status = TaskStatus.RUNNING
        state.sandbox_status = "active"
        sandbox, note = await create_sandbox(workspace, self.settings, cow=cow)
        sandbox.cancel = self.cancel  # type: ignore[attr-defined]
        state.sandbox_backend = sandbox.name
        await on_event(sandbox_event(sandbox.name, "active", note=note))
        tools = build_tools(workspace, sandbox, self.settings)
        dynamic_loader = DynamicToolLoader(
            source,
            SandboxToolRunner(sandbox, timeout_sec=self.settings.sandbox_timeout_sec),
            timeout_sec=self.settings.sandbox_timeout_sec,
        )
        skill_registry = SkillRegistry(source, include_cursor=False)
        policy_engine = PolicyEngine.load(source)
        mcp_host: McpHost | None = None
        if test_command:
            from coderking.tools.test import RunTestsTool

            tools["run_tests"] = RunTestsTool(
                sandbox, self.settings.sandbox_timeout_sec, default_command=test_command
            )
        if not state.messages:
            state.messages = [
                {
                    "role": "system",
                    "content": resolve_system_prompt(self.settings, state.role),
                },
                {"role": "user", "content": prompt},
            ]
            state.messages, project_doc = inject_project_instructions(source, state.messages)
            if project_doc is not None:
                await on_event(
                    project_instructions_event(
                        project_doc.source,
                        project_doc.content_hash,
                        truncated=project_doc.truncated,
                    )
                )
            state.messages, injected_skills = inject_matching_skills(
                source,
                state.messages,
                prompt,
                registry=skill_registry,
            )
            for skill in injected_skills:
                await on_event(skill_injected_event(skill.manifest.name, truncated=skill.truncated))
        else:
            state.messages.append({"role": "user", "content": prompt})
            state.role = Role.PLANNER
            state.iteration = 0
            state.status = TaskStatus.RUNNING
            state.messages.append(
                {"role": "system", "content": resolve_system_prompt(self.settings, Role.PLANNER)}
            )
        await on_event(status_event(state.role, state.status))
        fsm = PhaseFSM()

        async def emit_phase(previous: LoopPhase, current: LoopPhase) -> None:
            await on_event(
                phase_change_event(
                    phase=current.value,
                    from_phase=previous.value if previous != current else None,
                )
            )

        try:
            mcp_host = await McpHost.connect(source)
            tools.update(mcp_host.tools())
            while state.iteration < self.settings.max_iterations:
                self.cancel.raise_if_cancelled()
                if cancel_requested(source, state.task_id):
                    self.cancel.cancel()
                    state.cancel_requested = True
                if (
                    state.status == TaskStatus.INTERRUPTED
                    or state.cancel_requested
                    or self.cancel.cancelled
                ):
                    self.cancel.cancel()
                    state.status = TaskStatus.INTERRUPTED
                    if (
                        cow is not None
                        and self.settings.sandbox_rollback_on_interrupt
                        and state.snapshot
                    ):
                        from coderking.diffing import restore_snapshot

                        restore_snapshot(workspace, state.snapshot)
                    if fsm.phase != LoopPhase.TERMINATED:
                        await fsm.advance(LoopEvent.TERMINATE, on_phase_change=emit_phase)
                    await on_event(done_event(False, "interrupted"))
                    persist_state(source, state)
                    return state
                persist_state(source, state)
                state.iteration += 1
                if fsm.phase == LoopPhase.RE_PERCEIVE:
                    await fsm.advance(LoopEvent.CONTINUE, on_phase_change=emit_phase)
                elif fsm.phase == LoopPhase.PERCEIVE:
                    await on_event(phase_change_event(phase=fsm.phase.value))
                if queues:
                    await _inject_steering(state, queues, on_event)
                recent_context = _recent_tool_context(state.messages)
                state.messages, injected_skills = inject_matching_skills(
                    source,
                    state.messages,
                    state.task,
                    recent_context,
                    registry=skill_registry,
                )
                for skill in injected_skills:
                    await on_event(
                        skill_injected_event(skill.manifest.name, truncated=skill.truncated)
                    )
                await fsm.advance(LoopEvent.CONTEXT_READY, on_phase_change=emit_phase)
                tools.update(wrap_dynamic_tools(dynamic_loader.refresh()))
                mcp_names = {n for n in tools if n.startswith("mcp_")}
                allowed = ROLE_TOOLS[state.role] | dynamic_loader.names() | mcp_names
                schemas = [tools[name].schema() for name in allowed if name in tools]
                complete = self.llm.complete
                try:
                    response = await complete(state.messages, schemas, cancel=self.cancel)
                except TypeError:
                    response = await complete(state.messages, schemas)
                state.token_input += response.prompt_tokens
                state.token_output += response.completion_tokens
                await on_event(token_event(state.token_input, state.token_output))
                if not response.tool_calls:
                    if response.content:
                        state.messages.append({"role": "assistant", "content": response.content})
                    await fsm.advance(LoopEvent.ASSISTANT_NO_TOOLS, on_phase_change=emit_phase)
                    state = await self._advance_without_tools(state, on_event, workspace)
                    if state.status in {
                        TaskStatus.SUCCEEDED,
                        TaskStatus.FAILED,
                        TaskStatus.INTERRUPTED,
                    }:
                        return state
                    continue
                state.messages.append(_assistant_tool_message(response))
                await fsm.advance(LoopEvent.ASSISTANT_WITH_TOOLS, on_phase_change=emit_phase)
                tool_calls = list(response.tool_calls)
                for index, call in enumerate(tool_calls):
                    self.cancel.raise_if_cancelled()
                    if state.status == TaskStatus.INTERRUPTED:
                        break
                    await self._run_tool(
                        state,
                        tools,
                        call,
                        on_event,
                        approve,
                        auto_approve,
                        workspace,
                        source,
                        policy_engine,
                        dynamic_loader,
                    )
                    if queues:
                        steered = await queues.drain_steering()
                        if steered:
                            await _inject_steering_messages(state, steered, on_event)
                            for rem in tool_calls[index + 1 :]:
                                skipped = f'Tool "{rem.name}" skipped due to steering.'
                                state.messages.append(_tool_message(rem, skipped))
                                await on_event(tool_event(rem.name, "skipped", preview=skipped))
                            break
                await fsm.advance(LoopEvent.TOOLS_DONE, on_phase_change=emit_phase)
                await fsm.advance(LoopEvent.RESULTS_APPENDED, on_phase_change=emit_phase)
                if state.status in {
                    TaskStatus.SUCCEEDED,
                    TaskStatus.FAILED,
                    TaskStatus.INTERRUPTED,
                }:
                    return state
            state.status = TaskStatus.FAILED
            state.errors.append("max iterations reached")
            if fsm.phase != LoopPhase.TERMINATED:
                await fsm.advance(LoopEvent.TERMINATE, on_phase_change=emit_phase)
            await on_event(error_event("max iterations reached"))
            await on_event(done_event(False, "max iterations reached"))
            return state
        except CancelledTask:
            state.status = TaskStatus.INTERRUPTED
            if cow is not None and self.settings.sandbox_rollback_on_interrupt and state.snapshot:
                from coderking.diffing import restore_snapshot

                restore_snapshot(workspace, state.snapshot)
            await on_event(done_event(False, "interrupted"))
            return state
        except Exception as exc:
            state.status = TaskStatus.FAILED
            state.errors.append(str(exc))
            await on_event(error_event(str(exc)))
            await on_event(done_event(False, str(exc)))
            return state
        finally:
            self._run_queues = None
            if mcp_host is not None:
                await mcp_host.close()
            await sandbox.close()
            state.sandbox_status = "idle"
            if cow is not None:
                if state.status == TaskStatus.SUCCEEDED:
                    cow.promote()
                cow.close()
            persist_state(source, state)

    async def _run_tool(
        self,
        state: AgentState,
        tools: dict,
        call: ToolCall,
        on_event: EventSink,
        approve: ApprovalFn | None,
        auto_approve: bool,
        workspace: Path,
        source: Path,
        policy_engine: PolicyEngine,
        dynamic_loader: DynamicToolLoader,
    ) -> None:
        tool = tools.get(call.name)
        if tool is None:
            tools.update(wrap_dynamic_tools(dynamic_loader.refresh()))
            tool = tools.get(call.name)
        dynamic_names = dynamic_loader.names()
        mcp_names = {n for n in tools if n.startswith("mcp_")}
        await on_event(tool_event(call.name, "running", arguments=call.arguments))
        if tool is None:
            output = f"unknown tool: {call.name}"
            ok = False
        elif (
            call.name not in ROLE_TOOLS[state.role]
            and call.name not in dynamic_names
            and call.name not in mcp_names
        ):
            output = f"tool {call.name} is not allowed in role {state.role}"
            ok = False
        else:
            legacy_approval = bool(getattr(tool, "requires_approval", False))
            decision = policy_engine.evaluate(
                call.name,
                call.arguments,
                legacy_requires_approval=legacy_approval,
            )
            await on_event(
                policy_event(
                    decision.action.value,
                    call.name,
                    decision.reason,
                    rule=decision.rule,
                    arguments=call.arguments,
                )
            )
            _audit_policy_decision(source, call.name, call.arguments, decision)
            if decision.action == PolicyAction.DENY:
                output = f"policy denied: {decision.reason}"
                ok = False
                state.messages.append(_tool_message(call, output))
                await on_event(tool_event(call.name, "denied", preview=output))
                return
            if decision.action == PolicyAction.ASK and not auto_approve:
                state.status = TaskStatus.WAITING_APPROVAL
                await on_event(approval_event(decision.reason, call.name, call.arguments))
                allowed = False
                if approve:
                    allowed = await approve(call.name, decision.reason, call.arguments)
                if not allowed:
                    output = "user rejected the operation"
                    ok = False
                    state.status = TaskStatus.RUNNING
                    state.messages.append(_tool_message(call, output))
                    await on_event(tool_event(call.name, "rejected"))
                    return
                state.status = TaskStatus.RUNNING
            if hasattr(tool, "sandbox"):
                tool.sandbox.cancel = self.cancel  # type: ignore[attr-defined]
            result = await tool.execute(**call.arguments)
            ok = result.ok
            output = result.output
            if call.name == "submit_plan":
                steps = call.arguments.get("steps") or []
                state.plan = [PlanItem(str(s)) for s in steps]
                await on_event(plan_event([{"title": i.title, "done": i.done} for i in state.plan]))
                await self._switch_role(state, Role.CODING, on_event)
            elif call.name == "submit_for_execution":
                state.mark_next_plan_item()
                await on_event(plan_event([{"title": i.title, "done": i.done} for i in state.plan]))
                await self._switch_role(state, Role.EXECUTION, on_event)
            elif call.name == "finish_task":
                await self._try_finish(
                    state, on_event, workspace, str(call.arguments.get("summary") or "done")
                )
            elif call.name == "request_repair":
                state.errors.append(str(call.arguments.get("reason") or "repair"))
                state.repair_count += 1
                await self._switch_role(state, Role.REPAIR, on_event)
            elif call.name == "continue_execution":
                await self._switch_role(state, Role.EXECUTION, on_event)
            elif call.name in {"shell"}:
                await on_event(terminal_event(output))
            elif call.name == "run_tests":
                state.test_results = output
                state.last_test_ok = ok
                await on_event(test_event(output))
                await on_event(terminal_event(output))
                if ok:
                    state.mark_next_plan_item()
                    await on_event(
                        plan_event([{"title": i.title, "done": i.done} for i in state.plan])
                    )
                    if all(item.done for item in state.plan):
                        await self._succeed_task(state, on_event, workspace, "tests passed")
                    else:
                        await self._switch_role(state, Role.REVIEWER, on_event)
                        state.messages.append(
                            {
                                "role": "system",
                                "content": _reviewer_context(state, workspace),
                            }
                        )
                else:
                    state.repair_count += 1
                    await self._switch_role(state, Role.REPAIR, on_event)
            if result.changed_file:
                state.mark_file(result.changed_file)
                await on_event(file_event(result.changed_file, result.action or "modified"))
        record = ToolRecord(name=call.name, arguments=call.arguments, output=output[:8000], ok=ok)
        state.tool_history.append(record)
        if self.memory:
            self.memory.append_event(state.task_id, {"tool": call.name, "ok": ok})
        state.messages.append(_tool_message(call, output[:12000]))
        await on_event(tool_event(call.name, "ok" if ok else "error", preview=output[:500]))

    async def _try_finish(
        self, state: AgentState, on_event: EventSink, workspace: Path, summary: str
    ) -> None:
        if state.last_test_ok is False:
            state.errors.append("finish_task rejected: tests failed")
            state.repair_count += 1
            await self._switch_role(state, Role.REPAIR, on_event)
            return
        if state.last_test_ok is None:
            state.errors.append("finish_task rejected: tests have not been run")
            await self._switch_role(state, Role.EXECUTION, on_event)
            return
        await self._succeed_task(state, on_event, workspace, summary)

    async def _succeed_task(
        self,
        state: AgentState,
        on_event: EventSink,
        workspace: Path,
        summary: str,
    ) -> None:
        queues = self._run_queues
        if queues and await _inject_follow_up(state, queues, on_event):
            return
        state.mark_plan_complete()
        await on_event(plan_event([{"title": i.title, "done": i.done} for i in state.plan]))
        state.status = TaskStatus.SUCCEEDED
        await on_event(done_event(True, summary + "\n" + unified_diff(workspace, state.snapshot)))

    async def _advance_without_tools(
        self, state: AgentState, on_event: EventSink, workspace: Path
    ) -> AgentState:
        if state.role == Role.PLANNER:
            await self._switch_role(state, Role.CODING, on_event)
        elif state.role == Role.CODING:
            await self._switch_role(state, Role.EXECUTION, on_event)
        elif state.role == Role.EXECUTION:
            await self._switch_role(state, Role.REVIEWER, on_event)
            state.messages.append(
                {"role": "system", "content": _reviewer_context(state, workspace)}
            )
        elif state.role == Role.REPAIR:
            await self._switch_role(state, Role.EXECUTION, on_event)
        else:
            state.messages.append(
                {
                    "role": "system",
                    "content": (
                        "You must call finish_task, request_repair, or continue_execution. "
                        "Text-only replies cannot complete the task."
                    ),
                }
            )
        return state

    async def _switch_role(self, state: AgentState, role: Role, on_event: EventSink) -> None:
        state.role = role
        state.messages.append({"role": "system", "content": f"[role={role.value}]"})
        await on_event(status_event(state.role, state.status))


def _reviewer_context(state: AgentState, workspace: Path) -> str:
    diff = unified_diff(workspace, state.snapshot)
    plan = "\n".join(f"{'✓' if i.done else '○'} {i.title}" for i in state.plan) or "(empty)"
    return (
        "Review context:\n"
        f"last_test_ok={state.last_test_ok}\n"
        f"test_results:\n{state.test_results or '(none)'}\n"
        f"plan:\n{plan}\n"
        f"git_diff:\n{diff or '(no diff)'}\n"
    )


def _assistant_tool_message(response: LLMResponse) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": response.content or None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in response.tool_calls
        ],
    }


def _tool_message(call: ToolCall, output: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call.id, "content": output}


async def _inject_steering_messages(
    state: AgentState,
    items: list[str],
    on_event: EventSink,
) -> None:
    for text in items:
        state.messages.append({"role": "user", "content": f"[steer] {text}"})
        await on_event(steer_event(text))


async def _inject_steering(
    state: AgentState,
    queues: RunMessageQueues,
    on_event: EventSink,
) -> None:
    items = await queues.drain_steering()
    if items:
        await _inject_steering_messages(state, items, on_event)


async def _inject_follow_up(
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


def _recent_tool_context(messages: list[dict[str, Any]], *, limit: int = 3) -> str:
    chunks: list[str] = []
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        chunks.append(str(message.get("content") or ""))
        if len(chunks) >= limit:
            break
    return "\n".join(reversed(chunks))


def _audit_policy_decision(
    workspace: Path,
    tool_name: str,
    arguments: dict[str, Any],
    decision: PolicyDecision,
) -> None:
    if decision.action.value == "allow":
        return
    try:
        from coderking_coding_agent.session.repo import SessionRepo

        repo = SessionRepo(workspace, session_id="policy-audit")
        repo.append(
            "audit",
            {
                "tool": tool_name,
                "arguments": arguments,
                "decision": decision.to_dict(),
            },
        )
    except OSError:
        return
