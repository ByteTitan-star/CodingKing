"""L3: transport adapters (CLI, HTTP/SSE, RPC, Desktop)."""

from __future__ import annotations

from coderking_transport.http.sse import format_sse_event, stream_task_events

LAYER = 3
LAYER_NAME = "transport"
__version__ = "0.1.0"

__all__ = ["LAYER", "LAYER_NAME", "__version__", "format_sse_event", "stream_task_events"]
