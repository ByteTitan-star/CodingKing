"""Facade re-export of L0 provider types (Issue #23 PR-2)."""

from __future__ import annotations

from typing import Any, Protocol

from coderking.runtime.cancel import CancellationToken
from coderking_llm.provider import LLMResponse, ToolCall

__all__ = ["LLMProvider", "LLMResponse", "ToolCall"]


class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        cancel: CancellationToken | None = None,
    ) -> LLMResponse: ...
