"""L3: transport adapters (CLI, HTTP/SSE, RPC, Desktop)."""

from __future__ import annotations

from coderking_transport.http.sse import format_sse_event, stream_task_events
from coderking_transport.tui import CoderKingTuiApp, ScrollbackLog, format_agent_event, run_tui_app

LAYER = 3
LAYER_NAME = "transport"
__version__ = "0.1.0"

__all__ = [
    "LAYER",
    "LAYER_NAME",
    "__version__",
    "CoderKingTuiApp",
    "ScrollbackLog",
    "format_agent_event",
    "format_sse_event",
    "run_tui_app",
    "stream_task_events",
]
