"""Atomic profile runs through L1 ``run_agent_loop``."""

from __future__ import annotations

from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.llm.provider import LLMResponse, ToolCall
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import TaskStatus
from coderking_coding_agent.runtime.atomic_l1 import AtomicL1Runtime


class ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.i = 0
        self.last_tools: list | None = None

    async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001, ARG002
        self.last_tools = tools
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
        "extension": "atomic",
    }
    data.update(kwargs)
    return Settings(**data)


@pytest.mark.asyncio
async def test_atomic_extension_uses_l1_runtime(tmp_path: Path) -> None:
    runtime = AgentRuntime(_settings(tmp_path), ScriptedLLM([LLMResponse("done", [])]))
    assert isinstance(runtime._backend, AtomicL1Runtime)


@pytest.mark.asyncio
async def test_swe_extension_uses_l2_harness(tmp_path: Path) -> None:
    runtime = AgentRuntime(
        _settings(tmp_path, extension="swe"),
        ScriptedLLM([LLMResponse("done", [])]),
    )
    assert not isinstance(runtime._backend, AtomicL1Runtime)


@pytest.mark.asyncio
async def test_atomic_l1_scripted_edit_loop(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    llm = ScriptedLLM(
        [
            LLMResponse(
                "",
                [
                    _call(
                        "edit",
                        path="calc.py",
                        old_string="return a - b",
                        new_string="return a + b",
                    )
                ],
            ),
            LLMResponse("fixed", []),
        ]
    )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    state = await AgentRuntime(_settings(tmp_path), llm).run(
        "fix add",
        tmp_path,
        on_event=on_event,
        auto_approve=True,
    )
    assert state.status == TaskStatus.SUCCEEDED
    assert "return a + b" in (tmp_path / "calc.py").read_text(encoding="utf-8")
    assert any(e.type == "tool_call" and e.payload.get("status") == "ok" for e in events)
    assert any(e.type == "done" for e in events)
    assert any(r.name == "edit" and r.ok for r in state.tool_history)
    names = {
        (t.get("function") or {}).get("name") for t in (llm.last_tools or []) if isinstance(t, dict)
    }
    assert names == {"read", "write", "edit", "bash"}
