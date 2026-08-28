"""L0 shared protocols — concrete providers land in later PRs (#25)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class StopReason(StrEnum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    LENGTH = "length"
    ABORTED = "aborted"
    ERROR = "error"


@dataclass(frozen=True)
class UsageStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class LLMMessage:
    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class StreamChunk:
    """Incremental stream unit emitted by StreamFn."""

    type: str
    delta: str = ""
    tool_call_index: int | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments_delta: str = ""
    stop_reason: StopReason | None = None
    usage: UsageStats | None = None
    error: str | None = None


class StreamFn(Protocol):
    async def __call__(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        *,
        model: str,
        signal: Any | None = None,
    ) -> Any:
        """Return an async iterator of StreamChunk (or awaitable yielding them)."""
        ...
