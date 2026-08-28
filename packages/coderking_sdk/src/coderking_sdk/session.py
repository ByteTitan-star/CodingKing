"""In-process AgentSession over TaskController.

Thread-safety: one AgentSession must be used from a single asyncio event loop.
Do not share a session across threads or loops.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

from coderking.config import Settings, load_settings
from coderking.controller import TaskController


class AgentSession:
    """Thin embed API: ``async for event in session.run(prompt)``."""

    def __init__(
        self,
        workspace: str | Path = ".",
        *,
        model: str | None = None,
        settings: Settings | None = None,
        llm: Any | None = None,
        auto_approve: bool = True,
        test_command: str | None = None,
    ) -> None:
        root = Path(workspace).expanduser().resolve()
        if settings is None:
            overrides: dict[str, Any] = {"workspace": root}
            if model is not None:
                overrides["model"] = model
            settings = load_settings(**overrides)
        elif model is not None:
            settings = settings.model_copy(update={"model": model, "workspace": root})
        else:
            settings = settings.model_copy(update={"workspace": root})
        self.settings = settings
        self.workspace = root
        self.auto_approve = auto_approve
        self.test_command = test_command
        self._controller = TaskController(settings, llm=llm)
        self._task_id: str | None = None
        self._closed = False

    @property
    def task_id(self) -> str | None:
        return self._task_id

    async def __aenter__(self) -> AgentSession:
        if self._closed:
            raise RuntimeError("AgentSession is closed")
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._task_id is not None:
            try:
                self._controller.interrupt(self._task_id)
            except KeyError:
                pass
        self._closed = True

    async def run(self, prompt: str) -> AsyncIterator[Mapping[str, Any]]:
        """Start a task and yield event records until the run completes."""
        if self._closed:
            raise RuntimeError("AgentSession is closed")
        managed = await self._controller.create_task(
            prompt,
            self.workspace,
            auto_approve=self.auto_approve,
            test_command=self.test_command,
        )
        self._task_id = managed.state.task_id
        async for record in self._controller.subscribe_records(self._task_id):
            yield record

    async def steer(self, content: str) -> None:
        if self._task_id is None:
            raise RuntimeError("no active task; call run() first")
        await self._controller.steer(self._task_id, content)

    async def follow_up(self, content: str) -> None:
        if self._task_id is None:
            raise RuntimeError("no active task; call run() first")
        await self._controller.follow_up(self._task_id, content)

    def abort(self) -> None:
        if self._task_id is None:
            return
        self._controller.interrupt(self._task_id)

    def status(self) -> dict[str, Any]:
        if self._task_id is None:
            raise RuntimeError("no active task; call run() first")
        return self._controller.public_task(self._task_id)
