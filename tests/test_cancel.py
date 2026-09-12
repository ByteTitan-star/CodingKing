import asyncio
from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.controller import ManagedTask, TaskController
from coderking.llm.provider import LLMResponse
from coderking.registry import cancel_requested, persist_state, request_cancel
from coderking.runtime.cancel import CancellationToken, CancelledTask, wait_or_cancel
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import AgentState, TaskStatus


@pytest.mark.asyncio
async def test_wait_or_cancel_raises() -> None:
    token = CancellationToken()

    async def slow() -> str:
        await asyncio.sleep(5)
        return "done"

    async def trip() -> None:
        await asyncio.sleep(0.05)
        token.cancel()

    asyncio.create_task(trip())
    with pytest.raises(CancelledTask):
        await wait_or_cancel(slow(), token)


@pytest.mark.asyncio
async def test_runtime_cancel_during_llm(tmp_path: Path) -> None:
    token = CancellationToken()

    class SlowLLM:
        async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001
            await wait_or_cancel(asyncio.sleep(8), cancel)
            return LLMResponse("", [])

    async def trip() -> None:
        await asyncio.sleep(0.1)
        token.cancel()

    asyncio.create_task(trip())
    settings = Settings(
        openai_api_key="x", sandbox_mode="local", workspace=tmp_path, max_iterations=3
    )
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    state = await AgentRuntime(settings, SlowLLM(), cancel=token).run(
        "noop",
        tmp_path,
        on_event=_noop,
        auto_approve=True,
    )
    assert state.status == TaskStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_interrupt_releases_pending_approval(tmp_path: Path) -> None:
    controller = TaskController(Settings(workspace=tmp_path, openai_api_key="x"))
    state = AgentState(task="wait", repository=str(tmp_path), task_id="approval-wait")
    managed = ManagedTask(state=state, workspace=tmp_path)
    managed.approval = asyncio.get_running_loop().create_future()
    controller.tasks[state.task_id] = managed

    controller.interrupt(state.task_id)

    assert managed.approval.done()
    assert managed.approval.result() is False
    assert state.status == TaskStatus.CANCELLING


def test_interrupt_does_not_rewrite_terminal_state(tmp_path: Path) -> None:
    controller = TaskController(Settings(workspace=tmp_path, openai_api_key="x"))
    state = AgentState(task="done", repository=str(tmp_path), task_id="done-task")
    state.status = TaskStatus.SUCCEEDED
    controller.tasks[state.task_id] = ManagedTask(state=state, workspace=tmp_path)

    controller.interrupt(state.task_id)

    assert state.status == TaskStatus.SUCCEEDED


def test_cancel_request_does_not_mark_terminal_task(tmp_path: Path) -> None:
    state = AgentState(task="done", repository=str(tmp_path), task_id="terminal-task")
    state.status = TaskStatus.SUCCEEDED
    persist_state(tmp_path, state)

    request_cancel(tmp_path, state.task_id)

    assert not cancel_requested(tmp_path, state.task_id)


@pytest.mark.asyncio
async def test_controller_retry_creates_child_run_with_context(tmp_path: Path) -> None:
    class CaptureLLM:
        def __init__(self) -> None:
            self.messages: list[dict] = []

        async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001, ARG002
            self.messages = list(messages)
            return LLMResponse("recovered", [])

    llm = CaptureLLM()
    controller = TaskController(
        Settings(workspace=tmp_path, openai_api_key="x", sandbox_mode="local"),
        llm=llm,
    )
    previous = AgentState(
        task="repair",
        repository=str(tmp_path),
        task_id="failed-run",
        session_id="session-a",
        messages=[
            {"role": "system", "content": "core"},
            {"role": "user", "content": "repair"},
            {"role": "assistant", "content": "failed attempt"},
        ],
    )
    previous.status = TaskStatus.FAILED
    controller.tasks[previous.task_id] = ManagedTask(state=previous, workspace=tmp_path)

    retried = await controller.retry(previous.task_id)
    async for _record in controller.subscribe_records(retried.state.task_id):
        pass

    assert retried.state.task_id != previous.task_id
    assert retried.state.parent_run_id == previous.task_id
    assert retried.state.session_id == previous.session_id
    assert retried.state.status == TaskStatus.SUCCEEDED
    assert any(item.get("content") == "failed attempt" for item in llm.messages)


@pytest.mark.asyncio
async def test_controller_retry_rejects_successful_task(tmp_path: Path) -> None:
    controller = TaskController(Settings(workspace=tmp_path, openai_api_key="x"))
    state = AgentState(task="done", repository=str(tmp_path), task_id="successful-run")
    state.status = TaskStatus.SUCCEEDED
    controller.tasks[state.task_id] = ManagedTask(state=state, workspace=tmp_path)

    with pytest.raises(ValueError, match="only failed or interrupted"):
        await controller.retry(state.task_id)


async def _noop(event) -> None:  # noqa: ANN001, ARG001
    return None
