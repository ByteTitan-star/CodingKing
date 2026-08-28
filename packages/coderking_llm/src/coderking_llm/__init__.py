"""L0: unified LLM adapter layer (streaming, retry, token accounting)."""

from __future__ import annotations

from coderking_llm.openai_compat import (
    OpenAICompatConfig,
    OpenAICompatProvider,
    parse_chat_completion,
)
from coderking_llm.protocols import (
    LLMMessage,
    StopReason,
    StreamChunk,
    StreamFn,
    UsageStats,
)
from coderking_llm.provider import LLMProvider, LLMResponse, ToolCall
from coderking_llm.retry import RetryPolicy, retry_async
from coderking_llm.sse import AssembledResponse, assemble_stream_chunks

LAYER = 0
LAYER_NAME = "llm"
__version__ = "0.1.0"

__all__ = [
    "LAYER",
    "LAYER_NAME",
    "AssembledResponse",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "OpenAICompatConfig",
    "OpenAICompatProvider",
    "RetryPolicy",
    "StopReason",
    "StreamChunk",
    "StreamFn",
    "ToolCall",
    "UsageStats",
    "assemble_stream_chunks",
    "parse_chat_completion",
    "retry_async",
    "__version__",
]
