"""Dynamic workflow: plan tool + subagent orchestration (Claude-Code-style)."""

from __future__ import annotations

from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.llm.provider import LLMResponse, ToolCall
from coderking.runtime.loop import AgentRuntime


class ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.i = 0
        self.tools_per_call: list[list[str]] = []
        self.messages_per_call: list[list] = []

    async def complete(self, messages, tools, cancel=None):  # noqa: ANN001, ARG002
        self.messages_per_call.append(list(messages))
        self.tools_per_call.append([t["function"]["name"] for t in tools])
        item = self.responses[min(self.i, len(self.responses) - 1)]
        self.i += 1
        return item


def _call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=f"{name}-{id(arguments)}", name=name, arguments=dict(arguments))


def _settings(workspace: Path, **kwargs: object) -> Settings:
    data = {
        "openai_api_key": "x",
        "sandbox_mode": "local",
        "workspace": workspace,
        "max_iterations": 10,
    }
    data.update(kwargs)
    return Settings(**data)


@pytest.mark.asyncio
async def test_workflow_tools_are_gated_behind_config(tmp_path: Path) -> None:
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    llm = ScriptedLLM([LLMResponse("done", [])])
    runtime = AgentRuntime(_settings(tmp_path), llm)
    await runtime.run("hi", tmp_path, on_event=on_event)
    assert "agent" not in llm.tools_per_call[0]
    assert "plan" not in llm.tools_per_call[0]

    llm_wf = ScriptedLLM([LLMResponse("done", [])])
    runtime_wf = AgentRuntime(_settings(tmp_path, dynamic_workflow=True), llm_wf)
    await runtime_wf.run("hi", tmp_path, on_event=on_event)
    tool_names = llm_wf.tools_per_call[0]
    assert "agent" in tool_names
    assert "plan" in tool_names
    assert {"read", "write", "edit", "bash"} <= set(tool_names)


@pytest.mark.asyncio
async def test_subagent_runs_with_restricted_surface_and_returns_summary(
    tmp_path: Path,
) -> None:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    llm = ScriptedLLM(
        [
            # parent turn 1: delegate an investigation to an explore subagent
            LLMResponse(
                "",
                [
                    _call(
                        "agent",
                        description="inspect calc",
                        prompt="Read calc.py and report what function it defines.",
                        agent_type="explore",
                    )
                ],
            ),
            # subagent turn 1: read the file
            LLMResponse("", [_call("read", path="calc.py")]),
            # subagent final reply
            LLMResponse("calc.py defines add(a, b) which returns a - b (a bug).", []),
            # parent final reply
            LLMResponse("inspected via subagent", []),
        ]
    )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    runtime = AgentRuntime(_settings(tmp_path, dynamic_workflow=True, subagent_max_turns=4), llm)
    state = await runtime.run("find the bug in calc.py", tmp_path, on_event=on_event)

    # parent sees the full orchestration surface, subagent only its restricted set
    assert {"agent", "plan", "read", "write", "edit", "bash"} <= set(llm.tools_per_call[0])
    subagent_tools = set(llm.tools_per_call[1])
    assert subagent_tools <= {"read", "bash", "shell"}
    assert "write" not in subagent_tools
    assert "agent" not in subagent_tools  # no nested spawning

    # subagent lifecycle events + marked inner tool calls reach the stream
    kinds = [e.type for e in events]
    assert "subagent_start" in kinds
    assert "subagent_end" in kinds
    start = next(e for e in events if e.type == "subagent_start")
    assert start.payload["description"] == "inspect calc"
    assert start.payload["agent_type"] == "explore"
    end = next(e for e in events if e.type == "subagent_end")
    assert end.payload["ok"] is True
    assert "add(a, b)" in end.payload["summary"]
    marked = [e for e in events if e.type == "tool_call" and e.payload.get("subagent")]
    assert any(e.payload["tool"] == "read" for e in marked)

    # the subagent's reply came back as the parent's tool result
    parent_turn3 = llm.messages_per_call[3]
    tool_result = next(m["content"] for m in parent_turn3 if m.get("role") == "tool")
    assert "[subagent:explore · inspect calc]" in tool_result
    assert "a bug" in tool_result

    assert state.status.value == "succeeded"


@pytest.mark.asyncio
async def test_unknown_agent_type_fails_the_tool_call(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse(
                "", [_call("agent", description="bad", prompt="do it", agent_type="wizard")]
            ),
            LLMResponse("recovered", []),
        ]
    )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    runtime = AgentRuntime(_settings(tmp_path, dynamic_workflow=True), llm)
    state = await runtime.run("try a bad subagent", tmp_path, on_event=on_event)

    parent_turn2 = llm.messages_per_call[1]
    tool_result = next(m["content"] for m in parent_turn2 if m.get("role") == "tool")
    assert "unknown agent_type" in tool_result
    assert state.status.value == "succeeded"


@pytest.mark.asyncio
async def test_plan_tool_updates_state_and_emits_event(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse(
                "",
                [
                    _call(
                        "plan",
                        items=[
                            {"title": "locate bug", "status": "in_progress"},
                            {"title": "fix and verify", "status": "pending"},
                        ],
                    )
                ],
            ),
            LLMResponse("planned", []),
        ]
    )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    runtime = AgentRuntime(_settings(tmp_path, dynamic_workflow=True), llm)
    state = await runtime.run("plan the fix", tmp_path, on_event=on_event)

    assert [item.title for item in state.plan] == ["locate bug", "fix and verify"]
    assert not state.plan[0].done
    updates = [e for e in events if e.type == "plan_update"]
    assert updates, "plan_update event missing"
    statuses = [item["status"] for item in updates[-1].payload["plan"]]
    assert statuses[0] == "in_progress"
    assert statuses[1] == "pending"
    assert state.status.value == "succeeded"


@pytest.mark.asyncio
async def test_plan_tool_rejects_invalid_status(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("plan", items=[{"title": "x", "status": "later"}])]),
            LLMResponse("ok", []),
        ]
    )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    runtime = AgentRuntime(_settings(tmp_path, dynamic_workflow=True), llm)
    await runtime.run("bad plan", tmp_path, on_event=on_event)

    parent_turn2 = llm.messages_per_call[1]
    tool_result = next(m["content"] for m in parent_turn2 if m.get("role") == "tool")
    assert "invalid status" in tool_result
