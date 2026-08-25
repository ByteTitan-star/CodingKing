from __future__ import annotations

import asyncio


class CancelledTask(Exception):
    """Raised when a task cancellation token is set."""


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


async def wait_or_cancel(coro, token: CancellationToken | None):  # noqa: ANN001
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
