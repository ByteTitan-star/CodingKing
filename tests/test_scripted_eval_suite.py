from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.evalkit.loader import discover_tasks
from coderking.evalkit.runner import run_eval_task, write_reports
from coderking.llm.provider import LLMResponse, ToolCall

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
    return ToolCall(
        id=f"{name}-{len(arguments)}-{id(arguments)}",
        name=name,
        arguments=dict(arguments),
    )


def _scripts(task_id: str) -> list[LLMResponse]:
    if task_id == "bug_fix_add":
        return [
            LLMResponse("", [_call("submit_plan", steps=["edit", "test", "review"])]),
            LLMResponse(
                "",
                [
                    _call(
                        "write_file",
                        path="calc.py",
                        content="def add(a, b):\n    return a + b\n",
                    )
                ],
            ),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            LLMResponse("", [_call("finish_task", summary="fixed add")]),
        ]
    if task_id == "feature_add_greet":
        return [
            LLMResponse("", [_call("submit_plan", steps=["implement", "test", "review"])]),
            LLMResponse(
                "",
                [
                    _call(
                        "write_file",
                        path="greet.py",
                        content='def greet(name: str) -> str:\n    return f"hello, {name}"\n',
                    )
                ],
            ),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            LLMResponse("", [_call("finish_task", summary="greet implemented")]),
        ]
    return [
        LLMResponse("", [_call("submit_plan", steps=["refactor", "test", "review"])]),
        LLMResponse(
            "",
            [
                _call(
                    "write_file",
                    path="geometry.py",
                    content=(
                        "def rect_area(w: int, h: int) -> int:\n"
                        "    return w * h\n\n"
                        "def box_area(w: int, h: int) -> int:\n"
                        "    return rect_area(w, h)\n\n"
                        "def square_area(side: int) -> int:\n"
                        "    return rect_area(side, side)\n"
                    ),
                )
            ],
        ),
        LLMResponse("", [_call("submit_for_execution")]),
        LLMResponse("", [_call("run_tests")]),
        LLMResponse("", [_call("finish_task", summary="refactored")]),
    ]


@pytest.mark.asyncio
async def test_scripted_eval_suite_writes_reports(tmp_path: Path) -> None:
    settings = Settings(openai_api_key="x", sandbox_mode="local", max_iterations=16)
    results = []
    for task, task_dir in discover_tasks(ROOT / "eval" / "tasks"):
        llm = ScriptedLLM(_scripts(task.task_id))
        results.append(await run_eval_task(task, task_dir, settings, llm))
    assert {row.category for row in results} >= {"bug_fix", "feature_add", "refactor"}
    assert all(row.test_pass for row in results)
    out = tmp_path / "reports"
    write_reports(
        results,
        out,
        extra={
            "llm": "scripted fixture (no live API key in this environment)",
            "docker_unit": "see tests/test_docker.py",
        },
    )
    write_reports(
        results,
        out,
        stem="phase1-report",
        extra={"llm": "scripted fixture (no live API key in this environment)"},
    )
