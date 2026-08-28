"""Deterministic and LLM-assisted context compression strategies."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from coderking_agent_core.types import AgentMessage

_EDIT_TOOLS = frozenset({"edit_file", "write_file", "create_file"})


@dataclass
class CompressionSummary:
    decisions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    open_tasks: list[str] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisions": list(self.decisions),
            "errors": list(self.errors),
            "open_tasks": list(self.open_tasks),
            "files_touched": list(self.files_touched),
        }

    def render_system_message(self) -> str:
        data = self.to_dict()
        return "[Context compression summary — earlier turns omitted]\n" + json.dumps(
            data, ensure_ascii=False, indent=2
        )


def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _collect_summary(early: list[AgentMessage]) -> CompressionSummary:
    summary = CompressionSummary()
    seen_files: set[str] = set()
    for msg in early:
        if msg.role == "assistant" and msg.content:
            snippet = msg.content.strip().replace("\n", " ")[:200]
            if snippet and len(summary.decisions) < 12:
                summary.decisions.append(snippet)
        if msg.role == "user" and msg.content and len(summary.open_tasks) < 8:
            summary.open_tasks.append(msg.content.strip()[:160])
        if msg.role == "tool" and msg.content:
            lower = msg.content.lower()
            if "error" in lower or "fail" in lower or "not found" in lower:
                summary.errors.append(msg.content.strip()[:240])
        for call in msg.tool_calls or []:
            fn = call.get("function") or {}
            name = str(fn.get("name") or "")
            if name not in _EDIT_TOOLS:
                continue
            args = _parse_tool_arguments(fn.get("arguments"))
            path = str(args.get("path") or "").strip()
            if path and path not in seen_files:
                seen_files.add(path)
                summary.files_touched.append(path)
    return summary


def phase_a_compress(
    messages: list[AgentMessage],
    *,
    keep_recent_messages: int = 20,
) -> tuple[list[AgentMessage], CompressionSummary]:
    """Keep recent tail; replace early history with one system summary message."""
    if keep_recent_messages <= 0 or len(messages) <= keep_recent_messages:
        return list(messages), CompressionSummary()

    early = messages[:-keep_recent_messages]
    recent = messages[-keep_recent_messages:]
    summary = _collect_summary(early)
    compression_msg = AgentMessage(
        role="system",
        content=summary.render_system_message(),
        meta={"compression": True, "structured": summary.to_dict()},
    )
    return [compression_msg, *recent], summary


def compression_summary_message(
    summary: CompressionSummary,
    *,
    structured: dict[str, Any] | None = None,
) -> AgentMessage:
    payload = structured if structured is not None else summary.to_dict()
    return AgentMessage(
        role="system",
        content=summary.render_system_message(),
        meta={"compression": True, "structured": payload},
    )
