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
        self.message_batches: list[list[dict]] = []

    async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001, ARG002
        self.message_batches.append(list(messages))
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
    )


@pytest.mark.asyncio
async def test_agent_session_run_yields_events(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("bash", command="python -m pytest -q")]),
            LLMResponse("tests green", []),
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
        assert status["run_id"] == session.run_id
        assert status["session_id"] == session.session_id
        assert status["timing"]["finished_at"]
        assert status["status"] == "succeeded"

    assert any(e.get("type") == "done" for e in events)
    assert session.task_id is not None
    assert session.status()["status"] == "succeeded"
    assert sdk_version.startswith("1.")


@pytest.mark.asyncio
async def test_agent_session_carries_history_into_distinct_runs(tmp_path: Path) -> None:
    llm = ScriptedLLM([LLMResponse("first answer", []), LLMResponse("second answer", [])])
    async with AgentSession(
        workspace=tmp_path,
        settings=_settings(tmp_path),
        llm=llm,
        auto_approve=True,
    ) as session:
        async for _event in session.run("first request"):
            pass
        first_run = session.run_id
        async for _event in session.run("second request"):
            pass
        second_run = session.run_id

    assert first_run and second_run and first_run != second_run
    second_messages = llm.message_batches[-1]
    assert [item.get("content") for item in second_messages if item["role"] == "user"] == [
        "first request",
        "second request",
    ]
    assert any(item.get("content") == "first answer" for item in second_messages)


@pytest.mark.asyncio
async def test_agent_session_steer(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
    llm = ScriptedLLM([LLMResponse("ok", [])])
    async with AgentSession(
        workspace=tmp_path,
        settings=_settings(tmp_path),
        llm=llm,
        auto_approve=True,
    ) as session:
        async for _event in session.run("noop"):
            pass
        await session.steer("focus on tests")
        assert session.task_id is not None
