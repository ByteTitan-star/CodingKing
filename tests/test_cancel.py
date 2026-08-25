import asyncio
from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.llm.provider import LLMResponse
from coderking.runtime.cancel import CancellationToken, CancelledTask, wait_or_cancel
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import TaskStatus


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


async def _noop(event) -> None:  # noqa: ANN001, ARG001
    return None
