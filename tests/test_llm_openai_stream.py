from __future__ import annotations

import httpx
import pytest

from coderking_llm.openai_stream import complete_chat_streaming
from coderking_llm.protocols import StopReason
from coderking_llm.retry import RetryPolicy


@pytest.mark.asyncio
async def test_complete_chat_streaming_assembles_mock_sse() -> None:
    body = (
        'data: {"choices":[{"delta":{"content":"Hi "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"there"},'
        '"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        payload = request.read()
        assert b'"stream": true' in payload or b'"stream":true' in payload
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.example") as client:
        result = await complete_chat_streaming(
            client=client,
            url="https://api.example/v1/chat/completions",
            headers={"Authorization": "Bearer x"},
            payload={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
            policy=RetryPolicy(max_attempts=1),
        )
    assert result.content == "Hi there"
    assert result.stop_reason == StopReason.END_TURN
    assert result.usage.prompt_tokens == 3
    assert result.usage.completion_tokens == 2


@pytest.mark.asyncio
async def test_complete_chat_streaming_retries_503() -> None:
    calls = {"n": 0}
    ok_body = (
        'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, text=ok_body, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.example") as client:
        result = await complete_chat_streaming(
            client=client,
            url="https://api.example/v1/chat/completions",
            headers={},
            payload={"model": "m", "messages": []},
            policy=RetryPolicy(
                max_attempts=3, base_delay_sec=0.0, max_delay_sec=0.0, jitter_sec=0.0
            ),
        )
    assert result.content == "ok"
    assert calls["n"] == 2
