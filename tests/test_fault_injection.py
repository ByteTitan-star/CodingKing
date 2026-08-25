from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.evalkit.fault_injection import FirstRunTestsFaultInjector
from coderking.evalkit.loader import discover_tasks, load_task
from coderking.evalkit.repair_path import FAULTY_MULTIPLY, run_repair_path
from coderking.llm.provider import LLMResponse, ToolCall
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import Role, TaskStatus

ROOT = Path(__file__).resolve().parents[1]


class ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.i = 0

    async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001, ARG002
        item = self.responses[min(self.i, len(self.responses) - 1)]
        self.i += 1
        return item


def _call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=f"{name}-{id(arguments)}", name=name, arguments=dict(arguments))


def _settings(workspace: Path) -> Settings:
    return Settings(
        openai_api_key="x",
        sandbox_mode="local",
        workspace=workspace,
        max_iterations=20,
    )


@pytest.mark.asyncio
async def test_first_run_tests_injects_fault_then_repair(tmp_path: Path) -> None:
    (tmp_path / "multiply.py").write_text(
        "def multiply(a: int, b: int) -> int:\n    return a * b\n",
        encoding="utf-8",
    )
    (tmp_path / "test_multiply.py").write_text(
        "from multiply import multiply\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n",
        encoding="utf-8",
    )
    injector = FirstRunTestsFaultInjector(tmp_path, "multiply.py", FAULTY_MULTIPLY)
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("submit_plan", steps=["keep product", "test", "review"])]),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            LLMResponse("", [_call("request_repair", reason="product became sum")]),
            LLMResponse(
                "",
                [
                    _call(
                        "write_file",
                        path="multiply.py",
                        content="def multiply(a: int, b: int) -> int:\n    return a * b\n",
                    )
                ],
            ),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            LLMResponse("", [_call("finish_task", summary="restored product")]),
        ]
    )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    state = await AgentRuntime(_settings(tmp_path), llm).run(
        "keep multiply as product",
        tmp_path,
        on_event=on_event,
        auto_approve=True,
        test_command="python -m pytest -q",
        wrap_tools=injector.wrap,
    )
    tests = [e.payload.get("text", "") for e in events if e.type == "test_result"]
    assert injector.injected
    assert "exit=1" in str(tests[0]) or "failed" in str(tests[0]).lower()
    assert "exit=0" in str(tests[1])
    roles = [e.payload.get("role") for e in events if e.type == "agent_status"]
    fail_at = next(i for i, e in enumerate(events) if e.type == "test_result")
    after = [e.payload.get("role") for e in events[fail_at:] if e.type == "agent_status"]
    assert after[0] == Role.REVIEWER.value
    assert "repair" in roles
    assert "request_repair" in [r.name for r in state.tool_history]
    assert state.status == TaskStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_run_repair_path_records_injection_mode(tmp_path: Path) -> None:
    src = ROOT / "eval" / "repair_path" / "multiply"
    task, task_dir = load_task(src / "task.json")
    dest = tmp_path / "repo"
    dest.mkdir()
    (dest / "multiply.py").write_text((src / "repo" / "multiply.py").read_text(encoding="utf-8"))
    (dest / "test_multiply.py").write_text(
        (src / "repo" / "test_multiply.py").read_text(encoding="utf-8")
    )
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("submit_plan", steps=["keep", "test", "review"])]),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            LLMResponse("", [_call("request_repair", reason="fault")]),
            LLMResponse(
                "",
                [
                    _call(
                        "write_file",
                        path="multiply.py",
                        content="def multiply(a: int, b: int) -> int:\n    return a * b\n",
                    )
                ],
            ),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            LLMResponse("", [_call("finish_task", summary="ok")]),
        ]
    )
    report = await run_repair_path(task, dest, _settings(dest), llm)
    assert report["mode"] == "repair_fault_injection"
    assert report["success"] is True
    assert report["reviewer_decision"] == "request_repair"


def test_repair_path_not_in_coding_benchmark_suite() -> None:
    ids = {t.task_id for t, _ in discover_tasks(ROOT / "eval" / "tasks")}
    assert "repair_path_multiply" not in ids
    assert ids >= {"bug_fix_add", "feature_add_greet", "refactor_area"}
