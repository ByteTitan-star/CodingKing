"""Cancellation primitives for L1 agent loop and L2 sandbox."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable


class CancelledRun(Exception):
    """Raised when an agent run is aborted."""


class CancelledTask(Exception):
    """Raised when a task cancellation token is set."""


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


class CancellationToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise CancelledTask("task interrupted")


async def wait_or_cancel[T](coro: Awaitable[T], token: CancellationToken | None) -> T:
    if token is None:
        return await coro
    work = asyncio.ensure_future(coro)
    watcher = asyncio.ensure_future(token.wait())
    done, pending = await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
    for item in pending:
        item.cancel()
    if token.cancelled:
        work.cancel()
        try:
            await work
        except (asyncio.CancelledError, Exception):
            pass
        raise CancelledTask("task interrupted")
    return work.result()
