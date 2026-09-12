"""Loss-aware micro-compaction for old tool results."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import replace

from coderking_agent_core.types import AgentMessage


def _compacted_content(message: AgentMessage, content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]
    header = (
        "[Earlier tool output compacted "
        f"tool={message.name or 'unknown'} chars={len(content)} sha256={digest}]"
    )
    lowered = content.lower()
    if any(marker in lowered for marker in ("error", "failed", "exception", "traceback")):
        head = content[:400].strip()
        tail = content[-400:].strip() if len(content) > 400 else ""
        excerpts = "\n...\n".join(part for part in (head, tail) if part)
        return f"{header}\n{excerpts}"
    return header


def micro_compact_tool_outputs(
    messages: Sequence[AgentMessage],
    *,
    keep_recent_tool_results: int = 4,
    min_output_chars: int = 2_000,
) -> tuple[list[AgentMessage], int]:
    """Compact large, old tool results while retaining valid tool-role ordering."""
    if keep_recent_tool_results < 0:
        raise ValueError("keep_recent_tool_results must be non-negative")
    if min_output_chars < 1:
        raise ValueError("min_output_chars must be positive")
    updated = list(messages)
    tool_indexes = [index for index, message in enumerate(updated) if message.role == "tool"]
    protected = set(tool_indexes[-keep_recent_tool_results:]) if keep_recent_tool_results else set()
    compacted = 0
    for index in tool_indexes:
        message = updated[index]
        content = message.content or ""
        if (
            index in protected
            or len(content) < min_output_chars
            or message.meta.get("micro_compaction")
        ):
            continue
        updated[index] = replace(
            message,
            content=_compacted_content(message, content),
            meta={
                **message.meta,
                "micro_compaction": True,
                "original_chars": len(content),
            },
        )
        compacted += 1
    return updated, compacted
