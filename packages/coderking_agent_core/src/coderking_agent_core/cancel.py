"""Cancellation primitives for L1 agent loop."""

from __future__ import annotations

import asyncio


class CancelledRun(Exception):
    """Raised when an agent run is aborted."""


class RunCancel:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def abort(self) -> None:
        self._event.set()

    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    def raise_if_aborted(self) -> None:
        if self.aborted:
            raise CancelledRun("agent run aborted")

    async def wait_aborted(self) -> None:
        await self._event.wait()
