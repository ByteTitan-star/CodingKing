"""Wire TaskController into the L3 Textual TUI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from coderking.config import Settings
from coderking.controller import TaskController
from coderking_transport.tui.app import run_tui_app


class ControllerTuiSession:
    def __init__(
        self,
        workspace: Path,
        settings: Settings,
        *,
        auto_approve: bool = False,
        test_command: str | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings
        self.auto_approve = auto_approve
        self.test_command = test_command
        self.controller = TaskController(settings)

    async def start(self, prompt: str) -> str:
        task = await self.controller.create_task(
            prompt,
            self.workspace,
            auto_approve=self.auto_approve,
            test_command=self.test_command,
        )
        return task.state.task_id

    def events(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        return self.controller.subscribe_records(task_id)

    async def steer(self, task_id: str, content: str) -> None:
        await self.controller.steer(task_id, content)

    async def abort(self, task_id: str) -> None:
        self.controller.interrupt(task_id)


async def run_interactive_tui(
    workspace: Path,
    settings: Settings,
    *,
    auto_approve: bool = False,
    test_command: str | None = None,
) -> None:
    session = ControllerTuiSession(
        workspace,
        settings,
        auto_approve=auto_approve,
        test_command=test_command,
    )
    await run_tui_app(session, workspace_label=str(workspace.resolve()))
