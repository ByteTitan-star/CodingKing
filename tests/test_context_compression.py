from __future__ import annotations

import json
from typing import Any

import pytest

from coderking_agent_core.types import AgentMessage
from coderking_coding_agent.context.budget import TokenBudget, estimate_messages_tokens
from coderking_coding_agent.context.compress import phase_a_compress
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
