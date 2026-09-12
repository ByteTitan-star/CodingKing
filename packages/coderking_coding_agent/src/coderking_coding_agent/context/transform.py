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
from coderking_coding_agent.context.micro import micro_compact_tool_outputs
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
        micro_compaction_enabled: bool = True,
        micro_compaction_threshold: float = 0.5,
        micro_keep_recent_tool_results: int = 4,
        micro_min_output_chars: int = 2_000,
    ) -> None:
        self.budget = budget or TokenBudget()
        self.session_repo = session_repo
        self.summarize = summarize
        self.emit = emit
        self.keep_recent_messages = keep_recent_messages
        self.summarize_timeout_sec = summarize_timeout_sec
        self.micro_compaction_enabled = micro_compaction_enabled
        self.micro_compaction_threshold = micro_compaction_threshold
        self.micro_keep_recent_tool_results = micro_keep_recent_tool_results
        self.micro_min_output_chars = micro_min_output_chars

    async def transform(
        self,
        messages: Sequence[AgentMessage],
        *,
        force: bool = False,
    ) -> list[AgentMessage]:
        msgs = list(messages)
        before = estimate_messages_tokens(msgs)
        working = msgs
        micro_after = before
        micro_trigger = int(self.budget.max_prompt_tokens * self.micro_compaction_threshold)
        if self.micro_compaction_enabled and not force and before >= micro_trigger:
            working, compacted_count = micro_compact_tool_outputs(
                msgs,
                keep_recent_tool_results=self.micro_keep_recent_tool_results,
                min_output_chars=self.micro_min_output_chars,
            )
            micro_after = estimate_messages_tokens(working)
            if compacted_count and micro_after < before:
                if self.emit is not None:
                    await self.emit(
                        {
                            "type": "context_micro_compacted",
                            "before_tokens": before,
                            "after_tokens": micro_after,
                            "tool_results_compacted": compacted_count,
                        }
                    )
                if self.session_repo is not None:
                    self.session_repo.append(
                        "compression",
                        {
                            "strategy": "micro",
                            "messages": [
                                {
                                    "role": message.role,
                                    "content": message.content,
                                    "tool_calls": message.tool_calls,
                                    "tool_call_id": message.tool_call_id,
                                    "name": message.name,
                                    "meta": message.meta,
                                }
                                for message in working
                            ],
                            "before_tokens": before,
                            "after_tokens": micro_after,
                            "tool_results_compacted": compacted_count,
                        },
                    )

        if not force and not self.budget.should_compress(micro_after):
            return working
        if force and not working:
            return working
        if not force and not self.budget.should_compress(before) and working == msgs:
            return msgs

        compressed, summary = phase_a_compress(
            working, keep_recent_messages=self.keep_recent_messages
        )

        structured: dict[str, Any] | None = None
        if self.summarize is not None:
            early_count = max(0, len(working) - self.keep_recent_messages)
            early = working[:early_count]
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
                        active_skills=list(
                            structured.get("active_skills") or summary.active_skills
                        ),
                    )
                    compressed = [
                        compression_summary_message(summary, structured=structured),
                        *compressed[1:],
                    ]
            except Exception as exc:
                if self.emit is not None:
                    await self.emit(
                        {
                            "type": "context_compression_fallback",
                            "reason": str(exc),
                        }
                    )

        after = estimate_messages_tokens(compressed)
        if self.emit is not None and after < before:
            await self.emit(
                {
                    "type": "context_compressed",
                    "before_tokens": before,
                    "after_tokens": after,
                    "structured": summary.to_dict(),
                }
            )

        if self.session_repo is not None and after < before:
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
