from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.llm.provider import LLMResponse, ToolCall
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import TaskStatus


class ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.i = 0
        self.calls = 0

    async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001, ARG002
        self.calls += 1
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
async def test_harness_auto_finishes_when_tests_pass(tmp_path: Path) -> None:
    """Passing tests succeed without a Reviewer finish_task LLM round."""
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("submit_plan", steps=["fix add", "run tests"])]),
            LLMResponse(
                "",
                [_call("write_file", path="calc.py", content="def add(a, b):\n    return a + b\n")],
            ),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            # No finish_task — harness must complete.
        ]
    )
    state, events = await _collect(
        AgentRuntime(_settings(tmp_path), llm),
        "fix add",
        tmp_path,
        test_command="python -m pytest -q",
    )
    assert state.status == TaskStatus.SUCCEEDED
    assert "finish_task" not in [r.name for r in state.tool_history]
    assert any(e.type == "done" and e.payload.get("ok") for e in events)
    assert llm.calls == 4


@pytest.mark.asyncio
async def test_harness_routes_failed_tests_to_repair_without_request_repair(
    tmp_path: Path,
) -> None:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("submit_plan", steps=["edit", "test"])]),
            LLMResponse(
                "",
                [_call("write_file", path="calc.py", content="def add(a, b):\n    return a - b\n")],
            ),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            # Fail → harness Repair (no request_repair tool)
            LLMResponse(
                "",
                [_call("write_file", path="calc.py", content="def add(a, b):\n    return a + b\n")],
            ),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
        ]
    )
    state, events = await _collect(
        AgentRuntime(_settings(tmp_path), llm),
        "fix add",
        tmp_path,
        test_command="python -m pytest -q",
    )
    fail_idx = next(i for i, e in enumerate(events) if e.type == "test_result")
    roles_after_fail = [
        e.payload.get("role") for e in events[fail_idx:] if e.type == "agent_status"
    ]
    assert roles_after_fail[0] == "repair"
    assert "request_repair" not in [r.name for r in state.tool_history]
    assert state.repair_count >= 1
    assert state.status == TaskStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_finish_task_rejected_without_tests(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("submit_plan", steps=["noop"])]),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("ready", []),  # execution text → reviewer
            LLMResponse("", [_call("finish_task", summary="skip tests")]),
            LLMResponse("", [_call("run_tests")]),
        ]
    )
    state, _ = await _collect(
        AgentRuntime(_settings(tmp_path, max_iterations=10), llm),
        "finish without tests",
        tmp_path,
        test_command="python -m pytest -q",
    )
    assert any("finish_task rejected" in e for e in state.errors)
    assert state.status == TaskStatus.SUCCEEDED
    assert state.last_test_ok is True


@pytest.mark.asyncio
async def test_role_switch_uses_short_notes_not_full_prompt_spam(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("submit_plan", steps=["run"])]),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
        ]
    )
    state, _ = await _collect(
        AgentRuntime(_settings(tmp_path), llm),
        "noop",
        tmp_path,
        test_command="python -m pytest -q",
    )
    system_blobs = [m["content"] for m in state.messages if m.get("role") == "system"]
    full_planner = sum(
        1 for c in system_blobs if "CoderKing, a software-engineering agent" in str(c)
    )
    assert full_planner <= 1
    short_notes = [c for c in system_blobs if str(c).startswith("[role=")]
    assert short_notes, "expected short role switch notes"
