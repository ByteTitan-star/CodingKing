from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from coderking.config import Settings
from coderking.context.bm25 import BM25Index
from coderking.context.scanner import scan_repository
from coderking.diffing import snapshot_workspace, unified_diff
from coderking.llm.provider import LLMProvider, LLMResponse, ToolCall
from coderking.memory.store import MemoryStore
from coderking.registry import cancel_requested, persist_state
from coderking.runtime.cancel import CancellationToken, CancelledTask
from coderking.runtime.events import (
    AgentEvent,
    approval_event,
    done_event,
    error_event,
    file_event,
    plan_event,
    sandbox_event,
    status_event,
    terminal_event,
    test_event,
    token_event,
    tool_event,
)
from coderking.runtime.roles import ROLE_TOOLS, SYSTEM_PROMPTS
from coderking.runtime.state import AgentState, PlanItem, Role, TaskStatus, ToolRecord
from coderking.sandbox.manager import create_sandbox
from coderking.tools.registry import build_tools
from coderking.tools.shell import ShellTool

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
    ) -> AgentState:
        workspace = workspace.resolve()
        state = state or AgentState(task=prompt, repository=str(workspace))
        if not state.snapshot:
            state.snapshot = snapshot_workspace(workspace)
        state.status = TaskStatus.RUNNING
        state.sandbox_status = "active"
        sandbox, note = await create_sandbox(workspace, self.settings)
        sandbox.cancel = self.cancel  # type: ignore[attr-defined]
        state.sandbox_backend = sandbox.name
        await on_event(sandbox_event(sandbox.name, "active", note=note))
        tools = build_tools(workspace, sandbox, self.settings)
        if test_command:
            from coderking.tools.test import RunTestsTool

            tools["run_tests"] = RunTestsTool(
                sandbox, self.settings.sandbox_timeout_sec, default_command=test_command
            )
        summary = scan_repository(workspace)
        try:
            index = BM25Index(workspace)
            retrieved = index.search(prompt)
            context_hint = "\n".join(f"{path} ({score:.2f})" for path, score in retrieved)
        except OSError:
            context_hint = ""
        if not state.messages:
            state.messages = [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPTS[state.role]
                    + "\n\nRepository summary:\n"
                    + summary
                    + ("\n\nBM25 hits:\n" + context_hint if context_hint else ""),
                },
                {"role": "user", "content": prompt},
            ]
        else:
            state.messages.append({"role": "user", "content": prompt})
            state.role = Role.PLANNER
            state.iteration = 0
            state.status = TaskStatus.RUNNING
            state.messages.append({"role": "system", "content": SYSTEM_PROMPTS[Role.PLANNER]})
        await on_event(status_event(state.role, state.status))
        try:
            while state.iteration < self.settings.max_iterations:
                self.cancel.raise_if_cancelled()
                if cancel_requested(workspace, state.task_id):
                    self.cancel.cancel()
                    state.cancel_requested = True
                if (
                    state.status == TaskStatus.INTERRUPTED
                    or state.cancel_requested
                    or self.cancel.cancelled
                ):
                    self.cancel.cancel()
                    state.status = TaskStatus.INTERRUPTED
                    await on_event(done_event(False, "interrupted"))
                    persist_state(workspace, state)
                    return state
                persist_state(workspace, state)
                state.iteration += 1
                allowed = ROLE_TOOLS[state.role]
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
                    state = await self._advance_without_tools(state, on_event, workspace)
                    if state.status in {
                        TaskStatus.SUCCEEDED,
                        TaskStatus.FAILED,
                        TaskStatus.INTERRUPTED,
                    }:
                        return state
                    continue
                state.messages.append(_assistant_tool_message(response))
                for call in response.tool_calls:
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
                    )
                if state.status in {
                    TaskStatus.SUCCEEDED,
                    TaskStatus.FAILED,
                    TaskStatus.INTERRUPTED,
                }:
                    return state
            state.status = TaskStatus.FAILED
            state.errors.append("max iterations reached")
            await on_event(error_event("max iterations reached"))
            await on_event(done_event(False, "max iterations reached"))
            return state
        except CancelledTask:
            state.status = TaskStatus.INTERRUPTED
            await on_event(done_event(False, "interrupted"))
            return state
        except Exception as exc:
            state.status = TaskStatus.FAILED
            state.errors.append(str(exc))
            await on_event(error_event(str(exc)))
            await on_event(done_event(False, str(exc)))
            return state
        finally:
            await sandbox.close()
            state.sandbox_status = "idle"
            persist_state(workspace, state)

    async def _run_tool(
        self,
        state: AgentState,
        tools: dict,
        call: ToolCall,
        on_event: EventSink,
        approve: ApprovalFn | None,
        auto_approve: bool,
        workspace: Path,
    ) -> None:
        tool = tools.get(call.name)
        await on_event(tool_event(call.name, "running", arguments=call.arguments))
        if tool is None:
            output = f"unknown tool: {call.name}"
            ok = False
        elif call.name not in ROLE_TOOLS[state.role]:
            output = f"tool {call.name} is not allowed in role {state.role}"
            ok = False
        else:
            need = bool(getattr(tool, "requires_approval", False))
            if isinstance(tool, ShellTool) and tool.needs_approval(
                str(call.arguments.get("command", ""))
            ):
                need = True
            if need and not auto_approve:
                state.status = TaskStatus.WAITING_APPROVAL
                await on_event(approval_event("dangerous operation", call.name, call.arguments))
                allowed = False
                if approve:
                    allowed = await approve(call.name, "dangerous operation", call.arguments)
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
            state.messages.append(
                {
                    "role": "system",
                    "content": (
                        "Tests have not been run. "
                        "Call continue_execution or run_tests via Execution."
                    ),
                }
            )
            await self._switch_role(state, Role.EXECUTION, on_event)
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
        state.messages.append({"role": "system", "content": SYSTEM_PROMPTS[role]})
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
