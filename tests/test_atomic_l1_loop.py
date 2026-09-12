"""Atomic profile runs through L1 ``run_agent_loop``."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.llm.provider import LLMResponse, ToolCall
from coderking.registry import cancel_requested, request_cancel
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import AgentState, TaskStatus
from coderking_coding_agent.runtime.atomic_l1 import AtomicL1Runtime


class ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.i = 0
        self.last_tools: list | None = None
        self.last_messages: list = []

    async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001, ARG002
        self.last_messages = list(messages)
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
    }
    data.update(kwargs)
    return Settings(**data)


@pytest.mark.asyncio
async def test_default_runtime_uses_l1(tmp_path: Path) -> None:
    runtime = AgentRuntime(_settings(tmp_path), ScriptedLLM([LLMResponse("done", [])]))
    assert isinstance(runtime._backend, AtomicL1Runtime)


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
    assert state.changed_files == ["calc.py"]
    assert state.iteration == 2
    names = {
        (t.get("function") or {}).get("name") for t in (llm.last_tools or []) if isinstance(t, dict)
    }
    assert names == {"read", "write", "edit", "bash"}


@pytest.mark.asyncio
async def test_atomic_l1_denies_secret_path_write(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse(
                "",
                [_call("write", path=".env", content="SECRET=1")],
            ),
            LLMResponse("done", []),
        ]
    )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    state = await AgentRuntime(_settings(tmp_path), llm).run(
        "write secrets",
        tmp_path,
        on_event=on_event,
        auto_approve=True,
    )
    assert state.status == TaskStatus.SUCCEEDED
    assert not (tmp_path / ".env").exists()
    assert any(e.type == "policy_decision" and e.payload.get("action") == "deny" for e in events)
    assert any(r.name == "write" and not r.ok for r in state.tool_history)


@pytest.mark.asyncio
async def test_atomic_l1_denies_dangerous_bash(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("bash", command="rm -rf /")]),
            LLMResponse("done", []),
        ]
    )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    state = await AgentRuntime(_settings(tmp_path), llm).run(
        "destroy",
        tmp_path,
        on_event=on_event,
        auto_approve=True,
    )
    assert state.status == TaskStatus.SUCCEEDED
    assert any(e.type == "policy_decision" and e.payload.get("action") == "deny" for e in events)
    assert any(r.name == "bash" and not r.ok for r in state.tool_history)


@pytest.mark.asyncio
async def test_atomic_l1_ask_requires_approval(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("bash", command="git push origin main")]),
            LLMResponse("done", []),
        ]
    )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    state = await AgentRuntime(_settings(tmp_path), llm).run(
        "push",
        tmp_path,
        on_event=on_event,
        auto_approve=False,
        approve=None,
    )
    assert state.status == TaskStatus.SUCCEEDED
    assert any(e.type == "approval_required" for e in events)
    assert any(r.name == "bash" and not r.ok for r in state.tool_history)


@pytest.mark.asyncio
async def test_atomic_l1_ask_auto_approve_allows(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse("", [_call("bash", command="echo hi")]),
            LLMResponse("done", []),
        ]
    )
    # Use ask_patterns via workspace policy for a safe command.
    policy = tmp_path / ".coderking"
    policy.mkdir(parents=True)
    (policy / "policy.yaml").write_text(
        "tools:\n  bash:\n    ask_patterns:\n      - echo\\s+hi\n",
        encoding="utf-8",
    )
    approved: list[str] = []

    async def approve(name: str, reason: str, arguments: dict) -> bool:  # noqa: ANN001
        approved.append(name)
        return True

    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    state = await AgentRuntime(_settings(tmp_path), llm).run(
        "echo",
        tmp_path,
        on_event=on_event,
        auto_approve=False,
        approve=approve,
    )
    assert state.status == TaskStatus.SUCCEEDED
    assert approved == ["bash"]
    assert any(r.name == "bash" and r.ok for r in state.tool_history)


@pytest.mark.asyncio
async def test_resumed_state_is_sent_to_llm_before_new_prompt(tmp_path: Path) -> None:
    llm = ScriptedLLM([LLMResponse("continued", [])])
    previous = AgentState(task="first", repository=str(tmp_path))
    previous.messages = [
        {"role": "system", "content": "old system prompt"},
        {"role": "user", "content": "first request"},
        {"role": "assistant", "content": "first answer"},
    ]
    state = await AgentRuntime(_settings(tmp_path), llm).run(
        "second request",
        tmp_path,
        on_event=lambda _event: _async_none(),
        auto_approve=True,
        state=previous,
    )

    sent = llm.last_messages
    assert [item["content"] for item in sent if item["role"] == "user"] == [
        "first request",
        "second request",
    ]
    assert any(item.get("content") == "first answer" for item in sent)
    assert sum(item["role"] == "system" for item in sent) == 1
    assert state.messages[-2]["content"] == "second request"


@pytest.mark.asyncio
async def test_runtime_activates_context_compression(tmp_path: Path) -> None:
    llm = ScriptedLLM([LLMResponse("continued", [])])
    previous = AgentState(task="long", repository=str(tmp_path))
    previous.messages = [{"role": "system", "content": "core"}]
    for index in range(30):
        previous.messages.extend(
            [
                {"role": "user", "content": f"request-{index} " + "x" * 200},
                {"role": "assistant", "content": f"answer-{index}"},
            ]
        )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    state = await AgentRuntime(
        _settings(
            tmp_path,
            context_window=2_000,
            compression_reserve_tokens=200,
            compression_threshold=0.5,
            compression_keep_recent_messages=6,
        ),
        llm,
    ).run(
        "continue",
        tmp_path,
        on_event=on_event,
        auto_approve=True,
        state=previous,
    )

    assert any(
        "Context compression summary" in str(item.get("content")) for item in llm.last_messages
    )
    assert state.compression_count == 1
    assert any(event.type == "context_compressed" for event in events)
    assert any((item.get("meta") or {}).get("compression") for item in state.messages)


@pytest.mark.asyncio
async def test_max_turns_marks_task_failed(tmp_path: Path) -> None:
    llm = ScriptedLLM([LLMResponse("", [_call("read", path="missing.py")])])
    state = await AgentRuntime(_settings(tmp_path, max_iterations=1), llm).run(
        "keep going",
        tmp_path,
        on_event=lambda _event: _async_none(),
        auto_approve=True,
    )

    assert state.status == TaskStatus.FAILED
    assert state.iteration == 1
    assert any("max turns reached" in error for error in state.errors)


@pytest.mark.asyncio
async def test_external_cancel_marker_interrupts_active_task(tmp_path: Path) -> None:
    class CancelAwareLLM:
        async def complete(self, messages, tools, cancel=None):  # noqa: ANN001, ARG002
            assert cancel is not None
            await cancel.wait()
            raise RuntimeError("cancelled by token")

    previous = AgentState(task="long", repository=str(tmp_path), task_id="cancel-me")
    run = AgentRuntime(_settings(tmp_path), CancelAwareLLM()).run(
        "wait",
        tmp_path,
        on_event=lambda _event: _async_none(),
        auto_approve=True,
        state=previous,
    )
    task = asyncio.create_task(run)
    await asyncio.sleep(0.3)
    request_cancel(tmp_path, previous.task_id)
    state = await task

    assert state.status == TaskStatus.INTERRUPTED
    assert not cancel_requested(tmp_path, previous.task_id)


async def _async_none() -> None:
    return None
