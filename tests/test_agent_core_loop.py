from __future__ import annotations

import pytest

from coderking_agent_core.agent import Agent
from coderking_agent_core.loop import TurnResult, new_tool_call
from coderking_agent_core.types import AgentContext, AgentMessage, AgentTool


@pytest.mark.asyncio
async def test_agent_loop_runs_tool_then_stops() -> None:
    calls = {"n": 0}

    async def echo(**kwargs: object) -> tuple[bool, str]:
        return True, f"ok:{kwargs}"

    async def complete_turn(ctx: AgentContext) -> TurnResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return TurnResult(
                content="",
                tool_calls=[new_tool_call("echo", {"x": 1})],
                stop_reason="tool_use",
            )
        return TurnResult(content="done", stop_reason="end_turn")

    agent = Agent(
        system_prompt="test",
        tools=[
            AgentTool(
                name="echo",
                description="echo",
                parameters={"type": "object", "properties": {}},
                execute=echo,
            )
        ],
        complete_turn=complete_turn,
        should_stop_after_turn=lambda ctx, turn, results: _async_true(),
    )
    events: list[str] = []
    agent.subscribe(lambda e: _record(events, e))
    ctx = await agent.prompt("hi")
    assert any(e == "tool_execution_end" for e in events)
    assert any(m.role == "tool" and "ok:" in (m.content or "") for m in ctx.messages)
    assert events[-1] == "agent_end"


@pytest.mark.asyncio
async def test_agent_loop_emits_phase_change_sequence() -> None:
    async def echo(**kwargs: object) -> tuple[bool, str]:
        return True, "ok"

    async def complete_turn(ctx: AgentContext) -> TurnResult:
        if not any(m.role == "tool" for m in ctx.messages):
            return TurnResult(tool_calls=[new_tool_call("echo", {"x": 1})], stop_reason="tool_use")
        return TurnResult(content="done")

    agent = Agent(
        tools=[AgentTool("echo", "", {}, echo)],
        complete_turn=complete_turn,
        should_stop_after_turn=lambda ctx, turn, results: _async_true(),
    )
    phases: list[str] = []

    async def collect(event: dict) -> None:
        if event.get("type") == "phase_change":
            phases.append(str(event.get("phase")))

    agent.subscribe(collect)
    await agent.prompt("hi")
    assert phases[0] == "perceive"
    assert "decide" in phases
    assert "act" in phases
    assert "observe" in phases
    assert phases[-1] == "re_perceive"


@pytest.mark.asyncio
async def test_agent_steering_skips_second_tool_in_sequential_mode() -> None:
    executed: list[str] = []

    async def tool_a(**kwargs: object) -> tuple[bool, str]:
        executed.append("a")
        return True, "a"

    async def tool_b(**kwargs: object) -> tuple[bool, str]:
        executed.append("b")
        return True, "b"

    async def complete_turn(ctx: AgentContext) -> TurnResult:
        if not any(m.role == "tool" for m in ctx.messages):
            return TurnResult(
                tool_calls=[
                    new_tool_call("a"),
                    new_tool_call("b"),
                ],
                stop_reason="tool_use",
            )
        return TurnResult(content="done")

    agent = Agent(
        tools=[
            AgentTool("a", "", {}, tool_a),
            AgentTool("b", "", {}, tool_b),
        ],
        complete_turn=complete_turn,
        tool_execution="sequential",
        should_stop_after_turn=lambda ctx, turn, results: _async_true(),
    )

    async def steer_after_first(event: dict) -> None:
        if event.get("type") == "tool_execution_end" and event.get("name") == "a":
            agent.steer(AgentMessage(role="user", content="change direction"))

    agent.subscribe(steer_after_first)
    await agent.prompt("go")
    assert executed == ["a"]


@pytest.mark.asyncio
async def test_agent_steering_skips_second_tool_in_parallel_mode() -> None:
    import asyncio

    executed: list[str] = []

    async def tool_a(**kwargs: object) -> tuple[bool, str]:
        executed.append("a")
        await asyncio.sleep(0.02)
        return True, "a"

    async def tool_b(**kwargs: object) -> tuple[bool, str]:
        await asyncio.sleep(0.1)
        executed.append("b")
        return True, "b"

    async def complete_turn(ctx: AgentContext) -> TurnResult:
        if not any(m.role == "tool" for m in ctx.messages):
            return TurnResult(
                tool_calls=[
                    new_tool_call("a"),
                    new_tool_call("b"),
                ],
                stop_reason="tool_use",
            )
        return TurnResult(content="done")

    agent = Agent(
        tools=[
            AgentTool("a", "", {}, tool_a),
            AgentTool("b", "", {}, tool_b),
        ],
        complete_turn=complete_turn,
        tool_execution="parallel",
        should_stop_after_turn=lambda ctx, turn, results: _async_true(),
    )

    async def steer_after_first(event: dict) -> None:
        if event.get("type") == "tool_execution_start" and event.get("name") == "a":
            agent.steer(AgentMessage(role="user", content="change direction"))

    agent.subscribe(steer_after_first)
    await agent.prompt("go")
    assert executed == ["a"]


@pytest.mark.asyncio
async def test_agent_follow_up_runs_after_stop() -> None:
    turns = {"n": 0}

    async def complete_turn(ctx: AgentContext) -> TurnResult:
        turns["n"] += 1
        last_user = [m for m in ctx.messages if m.role == "user"][-1].content
        return TurnResult(content=f"seen:{last_user}")

    agent = Agent(
        complete_turn=complete_turn,
        should_stop_after_turn=lambda ctx, turn, results: _async_true(),
        max_turns=4,
    )
    agent.follow_up(AgentMessage(role="user", content="second"))
    ctx = await agent.prompt("first")
    assert turns["n"] == 2
    assert any(m.content == "seen:second" for m in ctx.messages if m.role == "assistant")


async def _async_true() -> bool:
    return True


async def _record(events: list[str], event: dict) -> None:
    events.append(str(event.get("type")))
