from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx

from coderking.config import Settings
from coderking.llm.provider import LLMResponse, ToolCall
from coderking.runtime.cancel import CancellationToken, wait_or_cancel


class OpenAICompatProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        cancel: CancellationToken | None = None,
    ) -> LLMResponse:
        if not self.settings.openai_api_key:
            raise RuntimeError("CODERKING_OPENAI_API_KEY is missing")
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_tokens": 4096,
        }
        if self.settings.disable_thinking:
            payload["thinking"] = {"type": "disabled"}
            payload["enable_thinking"] = False
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        url = self.settings.openai_base_url.rstrip("/") + "/chat/completions"
        client = self._client or httpx.AsyncClient(timeout=120.0)
        owns = self._client is None
        try:
            response = await wait_or_cancel(client.post(url, headers=headers, json=payload), cancel)
            if response.status_code >= 400 and self.settings.disable_thinking:
                payload.pop("thinking", None)
                payload.pop("enable_thinking", None)
                response = await wait_or_cancel(
                    client.post(url, headers=headers, json=payload), cancel
                )
            response.raise_for_status()
            data = response.json()
        finally:
            if owns:
                await client.aclose()
        return parse_chat_completion(data)
        if not self.settings.openai_api_key:
            raise RuntimeError("CODERKING_OPENAI_API_KEY is missing")
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_tokens": 4096,
        }
        if self.settings.disable_thinking:
            payload["thinking"] = {"type": "disabled"}
            payload["enable_thinking"] = False
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        url = self.settings.openai_base_url.rstrip("/") + "/chat/completions"
        client = self._client or httpx.AsyncClient(timeout=120.0)
        owns = self._client is None
        try:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400 and self.settings.disable_thinking:
                payload.pop("thinking", None)
                payload.pop("enable_thinking", None)
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        finally:
            if owns:
                await client.aclose()
        return parse_chat_completion(data)


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
