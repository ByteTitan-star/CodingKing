"""L0 LLM completion types and provider protocol."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall]
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        should_abort: Callable[[], bool] | None = None,
    ) -> LLMResponse: ...
