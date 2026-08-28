"""Token budget estimation for context compression."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from coderking_agent_core.types import AgentMessage


@dataclass(frozen=True)
class TokenBudget:
    context_window: int = 128_000
    reserve_completion: int = 4096
    compress_threshold: float = 0.75

    @property
    def max_prompt_tokens(self) -> int:
        usable = max(0, self.context_window - self.reserve_completion)
        return int(usable * self.compress_threshold)

    def should_compress(self, token_count: int) -> bool:
        return token_count > self.max_prompt_tokens


def estimate_text_tokens(text: str) -> int:
    """Heuristic tokenizer (≈4 chars per token) without external deps."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_message_tokens(message: AgentMessage) -> int:
    total = estimate_text_tokens(message.content or "")
    if message.tool_calls:
        for call in message.tool_calls:
            fn = call.get("function") or {}
            total += estimate_text_tokens(str(fn.get("name") or ""))
            total += estimate_text_tokens(str(fn.get("arguments") or ""))
    total += estimate_text_tokens(message.name or "")
    total += estimate_text_tokens(message.tool_call_id or "")
    return total


def estimate_messages_tokens(messages: Sequence[AgentMessage]) -> int:
    return sum(estimate_message_tokens(m) for m in messages)
