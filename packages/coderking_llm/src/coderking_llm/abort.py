"""Abort helpers for L0 HTTP calls (no facade cancel dependency)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class AbortedRequest(Exception):
    """Raised when should_abort becomes true during an await."""


async def await_with_abort[T](
    coro: Awaitable[T],
    should_abort: Callable[[], bool] | None,
    *,
    poll_interval: float = 0.05,
) -> T:
    """Await ``coro``, cancelling it if ``should_abort()`` turns true."""
    if should_abort is None:
        return await coro

    task = asyncio.ensure_future(coro)
    try:
        while not task.done():
            if should_abort():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                raise AbortedRequest("request aborted")
            done, _ = await asyncio.wait({task}, timeout=poll_interval)
            if done:
                break
        return task.result()
    finally:
        if not task.done():
            task.cancel()
