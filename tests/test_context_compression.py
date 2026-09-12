from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from coderking_agent_core.types import AgentMessage
from coderking_coding_agent.context.budget import TokenBudget, estimate_messages_tokens
from coderking_coding_agent.context.compress import phase_a_compress
from coderking_coding_agent.context.micro import micro_compact_tool_outputs
from coderking_coding_agent.context.transform import ContextCompressor
from coderking_coding_agent.session import SessionRepo


def _long_transcript(turns: int, *, chars: int = 400) -> list[AgentMessage]:
    messages: list[AgentMessage] = []
    for i in range(turns):
        messages.append(AgentMessage(role="user", content=f"task-{i} " + ("x" * chars)))
        messages.append(
            AgentMessage(
                role="assistant",
                content=f"done-{i}",
                tool_calls=[
                    {
                        "id": f"c{i}",
                        "type": "function",
                        "function": {
                            "name": "edit_file",
                            "arguments": json.dumps({"path": f"src/f{i}.py"}),
                        },
                    }
                ],
            )
        )
        messages.append(
            AgentMessage(
                role="tool",
                content="edited",
                tool_call_id=f"c{i}",
                name="edit_file",
            )
        )
    return messages


def test_token_budget_threshold() -> None:
    budget = TokenBudget(context_window=10_000, reserve_completion=1000, compress_threshold=0.75)
    assert budget.max_prompt_tokens == 6750
    assert budget.should_compress(7000)
    assert not budget.should_compress(6000)


def test_estimate_messages_tokens() -> None:
    msgs = [AgentMessage(role="user", content="hello world")]
    assert estimate_messages_tokens(msgs) >= 2


def test_phase_a_keeps_recent_turns() -> None:
    messages = _long_transcript(30, chars=50)
    compressed, summary = phase_a_compress(messages, keep_recent_messages=6)
    assert len(compressed) < len(messages)
    assert summary.files_touched
    assert compressed[-1].role == "tool"
    assert any(m.meta.get("compression") for m in compressed)


def test_phase_a_does_not_split_assistant_tool_group() -> None:
    messages = [
        AgentMessage(role="system", content="core"),
        AgentMessage(role="user", content="old request"),
        AgentMessage(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"path":"a.py"}'},
                }
            ],
        ),
        AgentMessage(role="tool", content="file", tool_call_id="call-1", name="read"),
        AgentMessage(role="user", content="new request"),
        AgentMessage(role="assistant", content="answer"),
    ]
    compressed, _ = phase_a_compress(messages, keep_recent_messages=3)
    retained = [message for message in compressed if not message.meta.get("compression")]
    first_tool = next(index for index, message in enumerate(retained) if message.role == "tool")
    assert retained[first_tool - 1].role == "assistant"
    assert retained[first_tool - 1].tool_calls


def test_micro_compaction_keeps_tool_sequence_and_recent_results() -> None:
    messages = _long_transcript(8, chars=50)
    for message in messages:
        if message.role == "tool":
            message.content = "large output " + ("x" * 3_000)

    compacted, count = micro_compact_tool_outputs(
        messages,
        keep_recent_tool_results=2,
        min_output_chars=1_000,
    )

    assert count == 6
    assert [message.role for message in compacted] == [message.role for message in messages]
    tool_messages = [message for message in compacted if message.role == "tool"]
    assert all(message.meta.get("micro_compaction") for message in tool_messages[:-2])
    assert all(not message.meta.get("micro_compaction") for message in tool_messages[-2:])
    assert tool_messages[-1].content == messages[-1].content


@pytest.mark.asyncio
async def test_micro_compaction_emits_event_and_persists_replacement(tmp_path: Path) -> None:
    repo = SessionRepo(tmp_path, session_id="micro")
    messages = _long_transcript(8, chars=50)
    for message in messages:
        if message.role == "tool":
            message.content = "result " + ("y" * 3_000)
    events: list[dict[str, Any]] = []

    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    compressor = ContextCompressor(
        budget=TokenBudget(
            context_window=30_000,
            reserve_completion=1_000,
            compress_threshold=0.9,
        ),
        session_repo=repo,
        emit=emit,
        micro_compaction_threshold=0.1,
        micro_keep_recent_tool_results=2,
        micro_min_output_chars=1_000,
    )
    result = await compressor.transform(messages)

    assert any(event["type"] == "context_micro_compacted" for event in events)
    assert not any(event["type"] == "context_compressed" for event in events)
    assert len(repo.materialize_messages()) == len(result)
    assert any(node.payload.get("strategy") == "micro" for node in repo.walk_to_head())


@pytest.mark.asyncio
async def test_compressor_reduces_200_turn_transcript(tmp_path) -> None:
    budget = TokenBudget(context_window=8_000, reserve_completion=500, compress_threshold=0.75)
    messages = _long_transcript(200, chars=300)
    before = estimate_messages_tokens(messages)
    assert before > budget.max_prompt_tokens

    compressor = ContextCompressor(budget=budget, keep_recent_messages=12)
    result = await compressor.transform(messages)
    after = estimate_messages_tokens(result)
    assert after <= budget.max_prompt_tokens
    assert any(m.meta.get("compression") for m in result)


@pytest.mark.asyncio
async def test_compressor_writes_session_node(tmp_path) -> None:
    repo = SessionRepo(tmp_path)
    budget = TokenBudget(context_window=3_000, reserve_completion=200, compress_threshold=0.75)
    messages = _long_transcript(40, chars=200)
    compressor = ContextCompressor(budget=budget, session_repo=repo, keep_recent_messages=8)
    await compressor.transform(messages)

    chain = repo.walk_to_head()
    compression_nodes = [n for n in chain if n.kind == "compression"]
    assert len(compression_nodes) == 1
    payload = compression_nodes[0].payload
    assert "summary" in payload
    assert payload.get("before_tokens", 0) > payload.get("after_tokens", 0)


@pytest.mark.asyncio
async def test_compressor_emits_context_compressed_event() -> None:
    events: list[dict[str, Any]] = []
    budget = TokenBudget(context_window=3_000, reserve_completion=200, compress_threshold=0.75)
    messages = _long_transcript(40, chars=200)

    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    compressor = ContextCompressor(budget=budget, emit=emit, keep_recent_messages=8)
    await compressor.transform(messages)
    types = [e["type"] for e in events]
    assert "context_compressed" in types
