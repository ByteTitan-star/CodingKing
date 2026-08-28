"""L0 OpenAI-compatible provider — lives in coderking_llm (no facade Settings)."""

from __future__ import annotations

import httpx
import pytest

from coderking_llm.openai_compat import (
    OpenAICompatConfig,
    OpenAICompatProvider,
    parse_chat_completion,
)
from coderking_llm.provider import LLMResponse, ToolCall
from coderking_llm.retry import RetryPolicy


def test_parse_chat_completion_tools_and_usage() -> None:
    data = {
        "choices": [
            {
                "message": {
                    "content": "hi",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "function": {"name": "read", "arguments": '{"path":"a.py"}'},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    }
    result = parse_chat_completion(data)
    assert result.content == "hi"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 4
    assert result.tool_calls == [
        ToolCall(id="c1", name="read", arguments={"path": "a.py"}),
    ]


def test_parse_chat_completion_list_content() -> None:
    data = {
        "choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"text": "b"}]}}],
        "usage": {},
    }
    assert parse_chat_completion(data).content == "ab"


@pytest.mark.asyncio
async def test_l0_provider_streaming_complete() -> None:
    body = (
        'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":1,"completion_tokens":1}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.example") as client:
        provider = OpenAICompatProvider(
            OpenAICompatConfig(
                api_key="sk-test",
                base_url="https://api.example/v1",
                model="test-model",
            ),
            client=client,
            prefer_stream=True,
            retry_policy=RetryPolicy(max_attempts=1),
        )
        result = await provider.complete(
            [{"role": "user", "content": "hi"}],
            tools=[],
        )
    assert isinstance(result, LLMResponse)
    assert result.content == "ok"
    assert result.prompt_tokens == 1


@pytest.mark.asyncio
async def test_l0_provider_requires_api_key() -> None:
    provider = OpenAICompatProvider(
        OpenAICompatConfig(api_key="", base_url="https://api.example/v1", model="m")
    )
    with pytest.raises(RuntimeError, match="API key"):
        await provider.complete([], [])


@pytest.mark.asyncio
async def test_facade_reexports_provider_types() -> None:
    from coderking.llm.provider import LLMResponse as FacadeResponse
    from coderking.llm.provider import ToolCall as FacadeToolCall
    from coderking_llm.provider import LLMResponse as L0Response
    from coderking_llm.provider import ToolCall as L0ToolCall

    assert FacadeResponse is L0Response
    assert FacadeToolCall is L0ToolCall
