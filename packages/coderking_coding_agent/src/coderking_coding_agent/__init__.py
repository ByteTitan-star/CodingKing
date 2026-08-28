"""L2: coding-domain runtime (tools, session, extensions)."""

from __future__ import annotations

from coderking_coding_agent.tools.base import Tool, ToolResult
from coderking_coding_agent.workspace import SKIP_DIRS, ensure_inside, iter_files

LAYER = 2
LAYER_NAME = "coding_agent"
__version__ = "0.1.0"

__all__ = [
    "LAYER",
    "LAYER_NAME",
    "SKIP_DIRS",
    "Tool",
    "ToolResult",
    "ensure_inside",
    "iter_files",
    "__version__",
]
