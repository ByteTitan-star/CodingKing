"""Exponential backoff retry for LLM HTTP calls."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_sec: float = 0.5
    max_delay_sec: float = 30.0
    jitter_sec: float = 0.25
    max_retry_delay_sec: float | None = 60.0

    def delay_for_attempt(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None and retry_after >= 0:
            delay = retry_after
            if self.max_retry_delay_sec is not None:
                delay = min(delay, self.max_retry_delay_sec)
        else:
            delay = min(self.max_delay_sec, self.base_delay_sec * (2 ** max(attempt - 1, 0)))
        if self.jitter_sec > 0:
            delay += random.uniform(0, self.jitter_sec)
        return max(delay, 0.0)


def is_retryable(exc: BaseException) -> bool:
    if isinstance(
        exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS
    return False


def _retry_after_seconds(exc: BaseException) -> float | None:
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    raw = exc.response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


async def retry_async[T](
    fn: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> T:
    policy = policy or RetryPolicy()
    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        if should_abort and should_abort():
            raise asyncio.CancelledError("retry aborted")
        try:
            return await fn()
        except BaseException as exc:
            last_exc = exc
            if attempt >= policy.max_attempts or not is_retryable(exc):
                raise
            delay = policy.delay_for_attempt(attempt, _retry_after_seconds(exc))
            # Sleep in small slices so abort is responsive.
            end = asyncio.get_running_loop().time() + delay
            while asyncio.get_running_loop().time() < end:
                if should_abort and should_abort():
                    raise asyncio.CancelledError("retry aborted") from exc
                await asyncio.sleep(min(0.05, end - asyncio.get_running_loop().time()))
    assert last_exc is not None
    raise last_exc
