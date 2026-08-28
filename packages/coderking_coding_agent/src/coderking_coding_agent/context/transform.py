"""L2 transform_context hook wiring for dynamic compression."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from coderking_agent_core.types import AgentMessage
from coderking_coding_agent.context.budget import TokenBudget, estimate_messages_tokens
from coderking_coding_agent.context.compress import (
    CompressionSummary,
    compression_summary_message,
    phase_a_compress,
)
from coderking_coding_agent.session.repo import SessionRepo

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]
SummarizeFn = Callable[[list[AgentMessage]], Awaitable[dict[str, Any]]]


class ContextCompressor:
    """Compress message history when estimated tokens exceed budget threshold."""

    def __init__(
        self,
        *,
        budget: TokenBudget | None = None,
        session_repo: SessionRepo | None = None,
        summarize: SummarizeFn | None = None,
        emit: EmitFn | None = None,
        keep_recent_messages: int = 20,
        summarize_timeout_sec: float = 30.0,
    ) -> None:
        self.budget = budget or TokenBudget()
        self.session_repo = session_repo
        self.summarize = summarize
        self.emit = emit
        self.keep_recent_messages = keep_recent_messages
        self.summarize_timeout_sec = summarize_timeout_sec

    async def transform(self, messages: Sequence[AgentMessage]) -> list[AgentMessage]:
        msgs = list(messages)
        before = estimate_messages_tokens(msgs)
        if not self.budget.should_compress(before):
            return msgs

        compressed, summary = phase_a_compress(msgs, keep_recent_messages=self.keep_recent_messages)

        structured: dict[str, Any] | None = None
        if self.summarize is not None:
            early_count = max(0, len(msgs) - self.keep_recent_messages)
            early = msgs[:early_count]
            try:
                structured = await asyncio.wait_for(
                    self.summarize(early),
                    timeout=self.summarize_timeout_sec,
                )
                if isinstance(structured, dict):
                    summary = CompressionSummary(
                        decisions=list(structured.get("decisions") or summary.decisions),
                        errors=list(structured.get("errors") or summary.errors),
                        open_tasks=list(structured.get("open_tasks") or summary.open_tasks),
                        files_touched=list(
                            structured.get("files_touched") or summary.files_touched
                        ),
                    )
                    compressed = [
                        compression_summary_message(summary, structured=structured),
                        *compressed[1:],
                    ]
            except (TimeoutError, Exception):
                pass

        after = estimate_messages_tokens(compressed)
        if self.emit is not None:
            await self.emit(
                {
                    "type": "context_compressed",
                    "before_tokens": before,
                    "after_tokens": after,
                    "structured": summary.to_dict(),
                }
            )

        if self.session_repo is not None:
            summary_msg = (
                compressed[0] if compressed and compressed[0].meta.get("compression") else None
            )
            self.session_repo.append(
                "compression",
                {
                    "summary": {
                        "role": "system",
                        "content": summary_msg.content
                        if summary_msg
                        else summary.render_system_message(),
                        "meta": summary_msg.meta if summary_msg else {"compression": True},
                    },
                    "structured": summary.to_dict(),
                    "before_tokens": before,
                    "after_tokens": after,
                },
            )

        return compressed


def make_transform_context(compressor: ContextCompressor):
    """Factory for L1 AgentLoopConfig.transform_context."""

    async def transform(messages: Sequence[AgentMessage]) -> list[AgentMessage]:
        return await compressor.transform(messages)

    return transform
