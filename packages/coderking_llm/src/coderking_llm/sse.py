"""SSE parsing for OpenAI-compatible chat.completion streams."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from coderking_llm.protocols import StopReason, StreamChunk, UsageStats


def iter_sse_json_payloads(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from SSE `data:` lines; ignore comments and [DONE]."""
    data_buf: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if data_buf:
                payload = "\n".join(data_buf)
                data_buf.clear()
                if payload.strip() == "[DONE]":
                    continue
                yield json.loads(payload)
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_buf.append(line[5:].lstrip())
            continue
        # Non-standard single-line JSON without blank terminator
        if line.startswith("{") and not data_buf:
            yield json.loads(line)
    if data_buf:
        payload = "\n".join(data_buf)
        if payload.strip() != "[DONE]":
            yield json.loads(payload)


def _map_finish_reason(raw: str | None) -> StopReason | None:
    if raw is None:
        return None
    mapping = {
        "stop": StopReason.END_TURN,
        "end_turn": StopReason.END_TURN,
        "tool_calls": StopReason.TOOL_USE,
        "function_call": StopReason.TOOL_USE,
        "length": StopReason.LENGTH,
        "content_filter": StopReason.ERROR,
    }
    return mapping.get(raw, StopReason.END_TURN)


def parse_openai_sse_chunk(payload: dict[str, Any]) -> list[StreamChunk]:
    chunks: list[StreamChunk] = []
    usage_raw = payload.get("usage")
    if usage_raw:
        chunks.append(
            StreamChunk(
                type="usage",
                usage=UsageStats(
                    prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
                    completion_tokens=int(usage_raw.get("completion_tokens") or 0),
                    cache_read_tokens=int(
                        (usage_raw.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
                    ),
                ),
            )
        )
    choices = payload.get("choices") or []
    if not choices:
        return chunks
    choice = choices[0]
    delta = choice.get("delta") or {}
    content = delta.get("content")
    if content:
        chunks.append(StreamChunk(type="text_delta", delta=str(content)))
    for tool in delta.get("tool_calls") or []:
        fn = tool.get("function") or {}
        chunks.append(
            StreamChunk(
                type="toolcall_delta",
                tool_call_index=int(tool.get("index") or 0),
                tool_call_id=str(tool["id"]) if tool.get("id") else None,
                tool_name=str(fn["name"]) if fn.get("name") else None,
                arguments_delta=str(fn.get("arguments") or ""),
            )
        )
    finish = _map_finish_reason(choice.get("finish_reason"))
    if finish is not None:
        chunks.append(StreamChunk(type="done", stop_reason=finish))
    return chunks


@dataclass
class AssembledToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssembledResponse:
    content: str
    tool_calls: list[AssembledToolCall] = field(default_factory=list)
    stop_reason: StopReason = StopReason.END_TURN
    usage: UsageStats = field(default_factory=UsageStats)


def assemble_stream_chunks(chunks: Iterable[StreamChunk]) -> AssembledResponse:
    text_parts: list[str] = []
    tools: dict[int, dict[str, str]] = {}
    stop = StopReason.END_TURN
    usage = UsageStats()
    for chunk in chunks:
        if chunk.type == "text_delta" and chunk.delta:
            text_parts.append(chunk.delta)
        elif chunk.type == "toolcall_delta":
            idx = int(chunk.tool_call_index or 0)
            slot = tools.setdefault(idx, {"id": "", "name": "", "arguments": ""})
            if chunk.tool_call_id:
                slot["id"] = chunk.tool_call_id
            if chunk.tool_name:
                slot["name"] = chunk.tool_name
            if chunk.arguments_delta:
                slot["arguments"] += chunk.arguments_delta
        elif chunk.type == "usage" and chunk.usage:
            usage = chunk.usage
        elif chunk.type == "done" and chunk.stop_reason:
            stop = chunk.stop_reason
            if chunk.usage:
                usage = chunk.usage
    assembled: list[AssembledToolCall] = []
    for idx in sorted(tools):
        slot = tools[idx]
        args_raw = slot["arguments"] or "{}"
        try:
            args = json.loads(args_raw)
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        if not isinstance(args, dict):
            args = {"value": args}
        assembled.append(
            AssembledToolCall(
                id=slot["id"] or str(uuid4()),
                name=slot["name"],
                arguments=args,
            )
        )
    if assembled and stop == StopReason.END_TURN:
        stop = StopReason.TOOL_USE
    return AssembledResponse(
        content="".join(text_parts),
        tool_calls=assembled,
        stop_reason=stop,
        usage=usage,
    )
