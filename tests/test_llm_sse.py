from __future__ import annotations

from coderking_llm.protocols import StopReason, StreamChunk, UsageStats
from coderking_llm.sse import assemble_stream_chunks, iter_sse_json_payloads, parse_openai_sse_chunk


def test_iter_sse_json_payloads_skips_comments_and_done() -> None:
    raw = ': keep-alive\ndata: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n'
    payloads = list(iter_sse_json_payloads(raw.splitlines(keepends=True)))
    assert len(payloads) == 1
    assert payloads[0]["choices"][0]["delta"]["content"] == "Hi"


def test_parse_openai_sse_chunk_text_and_tool_deltas() -> None:
    text_chunks = parse_openai_sse_chunk(
        {
            "choices": [{"delta": {"content": "Hello"}, "finish_reason": None}],
        }
    )
    assert text_chunks == [StreamChunk(type="text_delta", delta="Hello")]

    tool_chunks = parse_openai_sse_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read", "arguments": '{"p"'},
                            }
                        ]
                    }
                }
            ]
        }
    )
    assert tool_chunks[0].type == "toolcall_delta"
    assert tool_chunks[0].tool_call_id == "call_1"
    assert tool_chunks[0].tool_name == "read"
    assert tool_chunks[0].arguments_delta == '{"p"'


def test_assemble_stream_chunks_merges_text_and_tool_calls() -> None:
    chunks = [
        StreamChunk(type="text_delta", delta="A"),
        StreamChunk(type="text_delta", delta="B"),
        StreamChunk(
            type="toolcall_delta",
            tool_call_index=0,
            tool_call_id="c1",
            tool_name="edit",
            arguments_delta='{"path":"',
        ),
        StreamChunk(
            type="toolcall_delta",
            tool_call_index=0,
            arguments_delta='a.py"}',
        ),
        StreamChunk(
            type="done",
            stop_reason=StopReason.TOOL_USE,
            usage=UsageStats(10, 5),
        ),
    ]
    result = assemble_stream_chunks(chunks)
    assert result.content == "AB"
    assert result.stop_reason == StopReason.TOOL_USE
    assert result.usage.prompt_tokens == 10
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "edit"
    assert result.tool_calls[0].arguments == {"path": "a.py"}
