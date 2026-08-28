"""OpenAI-compatible chat completions provider (L0)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

from coderking_llm.abort import await_with_abort
from coderking_llm.openai_stream import complete_chat_streaming
from coderking_llm.provider import LLMResponse, ToolCall
from coderking_llm.retry import RetryPolicy, retry_async


@dataclass(frozen=True)
class OpenAICompatConfig:
    api_key: str
    base_url: str
    model: str
    disable_thinking: bool = False
    temperature: float = 0.2
    max_tokens: int = 4096


class OpenAICompatProvider:
    """HTTP provider with streaming + exponential retry; Settings-free."""

    def __init__(
        self,
        config: OpenAICompatConfig,
        client: httpx.AsyncClient | None = None,
        *,
        prefer_stream: bool = True,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.config = config
        self._client = client
        self.prefer_stream = prefer_stream
        self.retry_policy = retry_policy or RetryPolicy()

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        should_abort: Callable[[], bool] | None = None,
    ) -> LLMResponse:
        if not self.config.api_key:
            raise RuntimeError("OpenAI-compatible API key is missing")
        payload = self._build_payload(messages, tools)
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        client = self._client or httpx.AsyncClient(timeout=120.0)
        owns = self._client is None
        try:
            if self.prefer_stream:
                try:
                    assembled = await complete_chat_streaming(
                        client=client,
                        url=url,
                        headers=headers,
                        payload=payload,
                        policy=self.retry_policy,
                        should_abort=should_abort,
                    )
                    return LLMResponse(
                        content=assembled.content,
                        tool_calls=[
                            ToolCall(id=c.id, name=c.name, arguments=c.arguments)
                            for c in assembled.tool_calls
                        ],
                        prompt_tokens=assembled.usage.prompt_tokens,
                        completion_tokens=assembled.usage.completion_tokens,
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in {400, 404, 415, 501}:
                        raise
            return await self._complete_non_stream(
                client, url, headers, payload, should_abort
            )
        finally:
            if owns:
                await client.aclose()

    def _build_payload(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.disable_thinking:
            payload["thinking"] = {"type": "disabled"}
            payload["enable_thinking"] = False
        return payload

    async def _complete_non_stream(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        should_abort: Callable[[], bool] | None,
    ) -> LLMResponse:
        async def once() -> LLMResponse:
            response = await await_with_abort(
                client.post(url, headers=headers, json=payload), should_abort
            )
            if response.status_code >= 400 and self.config.disable_thinking:
                clean = dict(payload)
                clean.pop("thinking", None)
                clean.pop("enable_thinking", None)
                response = await await_with_abort(
                    client.post(url, headers=headers, json=clean), should_abort
                )
            response.raise_for_status()
            return parse_chat_completion(response.json())

        return await retry_async(once, policy=self.retry_policy, should_abort=should_abort)


def parse_chat_completion(data: dict[str, Any]) -> LLMResponse:
    choice = data["choices"][0]
    message = choice["message"]
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    usage = data.get("usage") or {}
    calls: list[ToolCall] = []
    for raw in message.get("tool_calls") or []:
        fn = raw.get("function") or {}
        args_raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        calls.append(
            ToolCall(
                id=str(raw.get("id") or uuid4()),
                name=str(fn.get("name") or ""),
                arguments=args if isinstance(args, dict) else {"value": args},
            )
        )
    return LLMResponse(
        content=str(content),
        tool_calls=calls,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )
