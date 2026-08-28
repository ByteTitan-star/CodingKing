"""Facade adapter: Settings + CancellationToken → L0 OpenAICompatProvider."""

from __future__ import annotations

from typing import Any

import httpx

from coderking.config import Settings
from coderking.llm.provider import LLMResponse
from coderking.runtime.cancel import CancellationToken
from coderking_llm.openai_compat import (
    OpenAICompatConfig,
    parse_chat_completion,
)
from coderking_llm.openai_compat import (
    OpenAICompatProvider as L0OpenAICompatProvider,
)
from coderking_llm.retry import RetryPolicy

__all__ = ["OpenAICompatProvider", "parse_chat_completion"]


class OpenAICompatProvider:
    """Compatible wrapper preserving the Phase-1 ``complete(..., cancel=)`` API."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        *,
        prefer_stream: bool = True,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.settings = settings
        self.prefer_stream = prefer_stream
        self.retry_policy = retry_policy or RetryPolicy()
        self._inner = L0OpenAICompatProvider(
            OpenAICompatConfig(
                api_key=settings.openai_api_key or "",
                base_url=settings.openai_base_url,
                model=settings.model,
                disable_thinking=bool(settings.disable_thinking),
            ),
            client=client,
            prefer_stream=prefer_stream,
            retry_policy=self.retry_policy,
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        cancel: CancellationToken | None = None,
    ) -> LLMResponse:
        if not self.settings.openai_api_key:
            raise RuntimeError("CODERKING_OPENAI_API_KEY is missing")
        should_abort = (lambda: cancel.cancelled) if cancel else None
        return await self._inner.complete(messages, tools, should_abort=should_abort)
