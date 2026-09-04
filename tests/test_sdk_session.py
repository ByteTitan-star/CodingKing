"""SDK session tests — no CLI subprocess."""

from __future__ import annotations

from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.llm.provider import LLMResponse, ToolCall
from coderking_sdk import AgentSession
from coderking_sdk import __version__ as sdk_version


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


def _settings(workspace: Path) -> Settings:
    return Settings(
        openai_api_key="x",
        sandbox_mode="local",
        workspace=workspace,
        max_iterations=12,
        extension="swe",
    )


@pytest.mark.asyncio
async def test_agent_session_run_yields_events(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("submit_plan", steps=["noop", "run tests"])]),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
            # harness auto-finishes when tests pass
        ]
    )
    events: list[dict] = []
    async with AgentSession(
        workspace=tmp_path,
        settings=_settings(tmp_path),
        llm=llm,
        auto_approve=True,
        test_command="python -m pytest -q",
    ) as session:
        async for event in session.run("keep tests green"):
            events.append(event)
        assert session.task_id is not None
        status = session.status()
        assert status["task_id"] == session.task_id
        assert status["status"] == "succeeded"

    assert any(e.get("type") == "done" for e in events)
    assert sdk_version.startswith("1.")


@pytest.mark.asyncio
async def test_agent_session_steer(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("submit_plan", steps=["a", "test"])]),
            LLMResponse("", [_call("submit_for_execution")]),
            LLMResponse("", [_call("run_tests")]),
        ]
    )
    async with AgentSession(
        workspace=tmp_path,
        settings=_settings(tmp_path),
        llm=llm,
        auto_approve=True,
        test_command="python -m pytest -q",
    ) as session:
        saw_steer = False
        async for event in session.run("work"):
            if event.get("type") == "agent_status":
                await session.steer("prefer minimal change")
            if event.get("type") == "steer":
                saw_steer = True
        assert saw_steer
