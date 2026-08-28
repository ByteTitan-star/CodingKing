"""Agent loop implementation (Pi agent-loop.ts equivalent)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from coderking_agent_core.cancel import CancelledRun, RunCancel
from coderking_agent_core.types import AgentContext, AgentMessage, LoopPhase

ToolExecutionMode = Literal["sequential", "parallel"]


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class TurnResult:
    content: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    stop_reason: str = "end_turn"
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class ToolExecutionResult:
    tool_call_id: str
    name: str
    ok: bool
    output: str


CompleteTurnFn = Callable[[AgentContext], Awaitable[TurnResult]]
TransformContextFn = Callable[[Sequence[AgentMessage]], Awaitable[list[AgentMessage]]]
SteeringFn = Callable[[], Awaitable[list[AgentMessage]]]
FollowUpFn = Callable[[], Awaitable[list[AgentMessage]]]
ShouldStopFn = Callable[[AgentContext, TurnResult, list[ToolExecutionResult]], Awaitable[bool]]


@dataclass
class AgentLoopConfig:
    complete_turn: CompleteTurnFn
    transform_context: TransformContextFn | None = None
    get_steering_messages: SteeringFn | None = None
    get_follow_up_messages: FollowUpFn | None = None
    should_stop_after_turn: ShouldStopFn | None = None
    max_turns: int = 24
    tool_execution: ToolExecutionMode = "parallel"
    cancel: RunCancel | None = None


async def run_agent_loop(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: Callable[[dict[str, Any]], Awaitable[None]],
    *,
    initial_messages: Sequence[AgentMessage] | None = None,
) -> AgentContext:
    """Run until stop, max_turns, cancel, or no follow-up."""
    ctx = AgentContext(
        system_prompt=context.system_prompt,
        messages=list(context.messages),
        tools=list(context.tools),
    )
    if initial_messages:
        for msg in initial_messages:
            ctx.messages.append(msg)
            await _emit_message(emit, msg)

    await emit({"type": "agent_start"})
    turns = 0
    pending: list[AgentMessage] = []

    while True:
        inner_active = True
        while inner_active or pending:
            if config.cancel:
                config.cancel.raise_if_aborted()
            if turns >= config.max_turns:
                await emit({"type": "error", "message": "max turns reached"})
                await emit({"type": "agent_end", "ok": False})
                return ctx
            turns += 1
            await emit({"type": "turn_start", "turn": turns})

            if pending:
                for msg in pending:
                    ctx.messages.append(msg)
                    await _emit_message(emit, msg)
                pending = []

            phase = LoopPhase.PERCEIVE
            await emit({"type": "phase_change", "phase": phase.value})
            messages_for_llm = list(ctx.messages)
            if config.transform_context:
                messages_for_llm = await config.transform_context(messages_for_llm)

            llm_ctx = AgentContext(
                system_prompt=ctx.system_prompt,
                messages=messages_for_llm,
                tools=ctx.tools,
            )

            phase = LoopPhase.DECIDE
            await emit({"type": "phase_change", "phase": phase.value})
            turn = await config.complete_turn(llm_ctx)
            assistant = AgentMessage(
                role="assistant",
                content=turn.content or None,
                tool_calls=[
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": json.dumps(c.arguments, ensure_ascii=False),
                        },
                    }
                    for c in turn.tool_calls
                ],
            )
            ctx.messages.append(assistant)
            await _emit_message(emit, assistant)
            await emit(
                {
                    "type": "token_usage",
                    "prompt": turn.prompt_tokens,
                    "completion": turn.completion_tokens,
                }
            )

            tool_results: list[ToolExecutionResult] = []
            steering_after_act: list[AgentMessage] = []
            inner_active = bool(turn.tool_calls)
            if turn.tool_calls:
                phase = LoopPhase.ACT
                await emit({"type": "phase_change", "phase": phase.value})
                if turn.stop_reason == "length":
                    tool_results = await _fail_truncated_tools(turn.tool_calls, emit)
                elif config.tool_execution == "parallel":
                    tool_results, steering_after_act = await _execute_tools_parallel(
                        ctx, turn.tool_calls, emit, config
                    )
                else:
                    tool_results, steering_after_act = await _execute_tools_sequential(
                        ctx, turn.tool_calls, emit, config
                    )

                phase = LoopPhase.OBSERVE
                await emit({"type": "phase_change", "phase": phase.value})
                for result in tool_results:
                    tool_msg = AgentMessage(
                        role="tool",
                        content=result.output,
                        tool_call_id=result.tool_call_id,
                        name=result.name,
                    )
                    ctx.messages.append(tool_msg)
                    await _emit_message(emit, tool_msg)

            phase = LoopPhase.RE_PERCEIVE
            await emit({"type": "phase_change", "phase": phase.value})
            await emit({"type": "turn_end", "turn": turns})

            if config.should_stop_after_turn and await config.should_stop_after_turn(
                ctx, turn, tool_results
            ):
                # Follow-up queue is checked in the outer loop before final exit.
                follow_up_pending = (
                    await config.get_follow_up_messages() if config.get_follow_up_messages else []
                )
                if not follow_up_pending:
                    await emit({"type": "agent_end", "ok": True})
                    return ctx
                pending = follow_up_pending
                continue

            steering = steering_after_act
            if not steering and config.get_steering_messages:
                steering = await config.get_steering_messages()
            if steering:
                pending = steering
                continue

            if not inner_active:
                break

        if config.get_follow_up_messages:
            follow_up = await config.get_follow_up_messages()
            if follow_up:
                pending = follow_up
                continue
        break

    await emit({"type": "agent_end", "ok": True})
    return ctx


async def _emit_message(
    emit: Callable[[dict[str, Any]], Awaitable[None]], msg: AgentMessage
) -> None:
    await emit({"type": "message_start", "message": _msg_to_dict(msg)})
    await emit({"type": "message_end", "message": _msg_to_dict(msg)})


def _msg_to_dict(msg: AgentMessage) -> dict[str, Any]:
    return {
        "role": msg.role,
        "content": msg.content,
        "tool_calls": msg.tool_calls,
        "tool_call_id": msg.tool_call_id,
        "name": msg.name,
    }


async def _fail_truncated_tools(
    calls: list[ToolCallRequest],
    emit: Callable[[dict[str, Any]], Awaitable[None]],
) -> list[ToolExecutionResult]:
    results: list[ToolExecutionResult] = []
    for call in calls:
        await emit(
            {
                "type": "tool_execution_start",
                "tool_call_id": call.id,
                "name": call.name,
                "arguments": call.arguments,
            }
        )
        output = (
            f'Tool "{call.name}" not executed: output token limit reached; '
            "re-issue with complete arguments."
        )
        await emit(
            {
                "type": "tool_execution_end",
                "tool_call_id": call.id,
                "name": call.name,
                "ok": False,
                "output": output,
            }
        )
        results.append(
            ToolExecutionResult(tool_call_id=call.id, name=call.name, ok=False, output=output)
        )
    return results


async def _execute_tools_parallel(
    ctx: AgentContext,
    calls: list[ToolCallRequest],
    emit: Callable[[dict[str, Any]], Awaitable[None]],
    config: AgentLoopConfig,
) -> tuple[list[ToolExecutionResult], list[AgentMessage]]:
    pending = [asyncio.create_task(_execute_one_tool(ctx, call, emit, config)) for call in calls]
    results: list[ToolExecutionResult] = []
    steering_found: list[AgentMessage] = []
    for task in asyncio.as_completed(pending):
        result = await task
        results.append(result)
        if config.get_steering_messages:
            steering = await config.get_steering_messages()
            if steering:
                steering_found = steering
                for other in pending:
                    if not other.done():
                        other.cancel()
                break
    if steering_found:
        done_ids = {r.tool_call_id for r in results}
        for call in calls:
            if call.id not in done_ids:
                output = f'Tool "{call.name}" skipped due to steering interrupt.'
                await emit(
                    {
                        "type": "tool_execution_end",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "ok": False,
                        "output": output,
                    }
                )
                results.append(
                    ToolExecutionResult(
                        tool_call_id=call.id, name=call.name, ok=False, output=output
                    )
                )
    return results, steering_found


async def _execute_tools_sequential(
    ctx: AgentContext,
    calls: list[ToolCallRequest],
    emit: Callable[[dict[str, Any]], Awaitable[None]],
    config: AgentLoopConfig,
) -> tuple[list[ToolExecutionResult], list[AgentMessage]]:
    results: list[ToolExecutionResult] = []
    steering_found: list[AgentMessage] = []
    for i, call in enumerate(calls):
        results.append(await _execute_one_tool(ctx, call, emit, config))
        if config.get_steering_messages:
            steering = await config.get_steering_messages()
            if steering:
                steering_found = steering
                for rem in calls[i + 1 :]:
                    output = f'Tool "{rem.name}" skipped due to steering interrupt.'
                    await emit(
                        {
                            "type": "tool_execution_end",
                            "tool_call_id": rem.id,
                            "name": rem.name,
                            "ok": False,
                            "output": output,
                        }
                    )
                    results.append(
                        ToolExecutionResult(
                            tool_call_id=rem.id, name=rem.name, ok=False, output=output
                        )
                    )
                break
    return results, steering_found


async def _execute_one_tool(
    ctx: AgentContext,
    call: ToolCallRequest,
    emit: Callable[[dict[str, Any]], Awaitable[None]],
    config: AgentLoopConfig,
) -> ToolExecutionResult:
    if config.cancel:
        config.cancel.raise_if_aborted()
    await emit(
        {
            "type": "tool_execution_start",
            "tool_call_id": call.id,
            "name": call.name,
            "arguments": call.arguments,
        }
    )
    tool_map = {t.name: t for t in ctx.tools}
    tool = tool_map.get(call.name)
    if tool is None:
        output = f"unknown tool: {call.name}"
        ok = False
    else:
        try:
            raw = await tool.execute(**call.arguments)
            if isinstance(raw, tuple) and len(raw) == 2:
                ok, output = bool(raw[0]), str(raw[1])
            else:
                ok, output = True, str(raw)
        except CancelledRun:
            raise
        except Exception as exc:
            ok, output = False, str(exc)
    await emit(
        {
            "type": "tool_execution_end",
            "tool_call_id": call.id,
            "name": call.name,
            "ok": ok,
            "output": output[:8000],
        }
    )
    return ToolExecutionResult(tool_call_id=call.id, name=call.name, ok=ok, output=output[:12000])


def new_tool_call(name: str, arguments: dict[str, Any] | None = None) -> ToolCallRequest:
    return ToolCallRequest(id=f"call_{uuid4().hex[:8]}", name=name, arguments=arguments or {})
