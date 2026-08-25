from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.llm.provider import LLMResponse, ToolCall
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import Role, TaskStatus


class ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.i = 0

    async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001, ARG002
        item = self.responses[min(self.i, len(self.responses) - 1)]
        self.i += 1
        return item


def _call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(
        id=f"{name}-{len(arguments)}-{id(arguments)}", name=name, arguments=dict(arguments)
    )


def _settings(workspace: Path, **kwargs: object) -> Settings:
    data = {
        "openai_api_key": "x",
        "sandbox_mode": "local",
        "workspace": workspace,
        "max_iterations": 20,
    }
    data.update(kwargs)
    return Settings(**data)


async def _collect(runtime: AgentRuntime, prompt: str, workspace: Path, **kwargs: object):
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    state = await runtime.run(prompt, workspace, on_event=on_event, auto_approve=True, **kwargs)
    return state, events


@pytest.mark.asyncio
async def test_scripted_bugfix_loop(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("submit_plan", steps=["fix add", "run tests", "review"])]),
            LLMResponse(
                "",
                [_call("write_file", path="calc.py", content="def add(a, b):\n    return a + b\n")],
            ),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            LLMResponse("", [_call("finish_task", summary="fixed add")]),
        ]
    )
    state, events = await _collect(
        AgentRuntime(_settings(tmp_path), llm),
        "fix add",
        tmp_path,
        test_command="python -m pytest -q",
    )
    assert state.status == TaskStatus.SUCCEEDED
    assert any(item.done for item in state.plan)
    assert "done" in [e.type for e in events]


@pytest.mark.asyncio
async def test_reviewer_without_tools_does_not_succeed(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("submit_plan", steps=["noop", "test", "review"])]),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            LLMResponse("I think it is done", []),
            LLMResponse("still thinking", []),
        ]
    )
    state, _ = await _collect(
        AgentRuntime(_settings(tmp_path, max_iterations=8), llm),
        "keep tests passing",
        tmp_path,
        test_command="python -m pytest -q",
    )
    assert state.status != TaskStatus.SUCCEEDED
    assert state.role == Role.REVIEWER


@pytest.mark.asyncio
async def test_failed_tests_go_repair_then_succeed(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("submit_plan", steps=["edit", "test", "review"])]),
            LLMResponse(
                "",
                [_call("write_file", path="calc.py", content="def add(a, b):\n    return a - b\n")],
            ),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            LLMResponse("", [_call("request_repair", reason="add is still subtraction")]),
            LLMResponse(
                "",
                [_call("write_file", path="calc.py", content="def add(a, b):\n    return a + b\n")],
            ),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            LLMResponse("", [_call("finish_task", summary="repaired add")]),
        ]
    )
    state, events = await _collect(
        AgentRuntime(_settings(tmp_path), llm),
        "fix add",
        tmp_path,
        test_command="python -m pytest -q",
    )
    roles = [e.payload.get("role") for e in events if e.type == "agent_status"]
    fail_idx = next(
        i
        for i, e in enumerate(events)
        if e.type == "test_result" and "exit=" in str(e.payload.get("text", ""))
    )
    roles_after_fail = [
        e.payload.get("role") for e in events[fail_idx:] if e.type == "agent_status"
    ]
    assert roles_after_fail[0] == "reviewer"
    assert "repair" in roles
    tools = [r.name for r in state.tool_history]
    assert "request_repair" in tools
    assert state.status == TaskStatus.SUCCEEDED
    assert (tmp_path / "calc.py").read_text(encoding="utf-8").find("+") != -1
    assert all(item.done for item in state.plan)
