from __future__ import annotations

import asyncio

import httpx
import pytest

from coderking_llm.retry import RetryPolicy, retry_async


@pytest.mark.asyncio
async def test_retry_async_retries_429_then_succeeds() -> None:
    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            response = httpx.Response(
                429, headers={"Retry-After": "0"}, request=httpx.Request("GET", "http://x")
            )
            raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        return "ok"

    policy = RetryPolicy(max_attempts=5, base_delay_sec=0.0, max_delay_sec=0.0, jitter_sec=0.0)
    assert await retry_async(flaky, policy=policy) == "ok"
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_retry_async_does_not_retry_400() -> None:
    async def bad() -> str:
        response = httpx.Response(400, request=httpx.Request("POST", "http://x"))
        raise httpx.HTTPStatusError("bad request", request=response.request, response=response)

    policy = RetryPolicy(max_attempts=5, base_delay_sec=0.0, max_delay_sec=0.0, jitter_sec=0.0)
    with pytest.raises(httpx.HTTPStatusError):
        await retry_async(bad, policy=policy)


@pytest.mark.asyncio
async def test_retry_async_respects_cancel() -> None:
    cancelled = asyncio.Event()

    async def forever() -> str:
        response = httpx.Response(503, request=httpx.Request("GET", "http://x"))
        raise httpx.HTTPStatusError("unavailable", request=response.request, response=response)

    policy = RetryPolicy(max_attempts=10, base_delay_sec=60.0, max_delay_sec=60.0, jitter_sec=0.0)

    async def run() -> None:
        await retry_async(forever, policy=policy, should_abort=cancelled.is_set)

    task = asyncio.create_task(run())
    await asyncio.sleep(0.01)
    cancelled.set()
    with pytest.raises(asyncio.CancelledError):
        await task
