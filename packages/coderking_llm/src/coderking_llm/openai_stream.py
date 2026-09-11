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


def api_error_detail(response: httpx.Response) -> str:
    """Extract the provider's own error message (e.g. quota/balance codes)."""
    try:
        data = response.json()
        err = data.get("error") if isinstance(data.get("error"), dict) else {}
        code = err.get("code") or data.get("code")
        message = err.get("message") or data.get("message")
        if message:
            suffix = f" (code {code})" if code is not None else ""
            return f"HTTP {response.status_code}: {message}{suffix}"
    except Exception:
        pass
    return ""


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

    response_cm = client.stream("POST", url, headers=headers, json=stream_payload)
    response = await response_cm.__aenter__()
    try:
        if response.status_code >= 400 and ("thinking" in payload or "enable_thinking" in payload):
            # Mirror the non-stream fallback: some models (e.g. always-thinking
            # GLM) reject explicit thinking controls; retry once without them.
            await response.aread()
            await response_cm.__aexit__(None, None, None)
            clean = {
                k: v for k, v in stream_payload.items() if k not in {"thinking", "enable_thinking"}
            }
            response_cm = client.stream("POST", url, headers=headers, json=clean)
            response = await response_cm.__aenter__()
        if response.status_code >= 400:
            await response.aread()
            detail = api_error_detail(response)
            if detail:
                raise RuntimeError(detail)
            response.raise_for_status()
        async for line in response.aiter_lines():
            if should_abort and should_abort():
                raise httpx.RequestError("stream aborted", request=response.request)
            # aiter_lines strips newlines; restore for parser contract
            for payload_obj in iter_sse_json_payloads([line + "\n", "\n"]):
                for chunk in parse_openai_sse_chunk(payload_obj):
                    yield chunk
    finally:
        await response_cm.__aexit__(None, None, None)


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
