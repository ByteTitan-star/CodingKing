"""TUI session protocol — implemented by Phase 1 facade."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol


class TuiAgentSession(Protocol):
    async def start(self, prompt: str) -> str:
        """Start a task; return task_id."""

    def events(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        """Stream agent event records for a task."""

    async def steer(self, task_id: str, content: str) -> None: ...

    async def abort(self, task_id: str) -> None: ...
