"""OpenAI-compatible streaming chat completions for L0."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from coderking_llm.protocols import StreamChunk
from coderking_llm.retry import RetryPolicy, retry_async
from coderking_llm.sse import (
    AssembledResponse,
    assemble_stream_chunks,
    iter_sse_json_payloads,
    parse_openai_sse_chunk,
)


async def stream_chat_completion(
    *,
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    should_abort: Callable[[], bool] | None = None,
) -> AsyncIterator[StreamChunk]:
    """Yield StreamChunks from an OpenAI-compatible SSE response body."""
    stream_payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}
    async with client.stream("POST", url, headers=headers, json=stream_payload) as response:
        if response.status_code >= 400:
            await response.aread()
            response.raise_for_status()
        async for line in response.aiter_lines():
            if should_abort and should_abort():
                raise httpx.RequestError("stream aborted", request=response.request)
            # aiter_lines strips newlines; restore for parser contract
            for payload_obj in iter_sse_json_payloads([line + "\n", "\n"]):
                for chunk in parse_openai_sse_chunk(payload_obj):
                    yield chunk


async def complete_chat_streaming(
    *,
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    policy: RetryPolicy | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> AssembledResponse:
    """Stream then assemble; retries only apply to connection/setup failures."""

    async def once() -> AssembledResponse:
        chunks: list[StreamChunk] = []
        async for chunk in stream_chat_completion(
            client=client,
            url=url,
            headers=headers,
            payload=payload,
            should_abort=should_abort,
        ):
            chunks.append(chunk)
        return assemble_stream_chunks(chunks)

    return await retry_async(once, policy=policy, should_abort=should_abort)
