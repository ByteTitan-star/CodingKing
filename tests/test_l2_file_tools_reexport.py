"""L2 owns file/edit tool implementations; facade re-exports the same types."""

from __future__ import annotations

from coderking.tools.base import Tool, ToolResult
from coderking.tools.edit import EditFileTool, apply_string_replace
from coderking.tools.file import ReadFileTool, WriteFileTool, invalidate_bytecode
from coderking.tools.read import format_numbered_lines, read_path
from coderking.workspace import SKIP_DIRS, ensure_inside, iter_files
from coderking_coding_agent.tools.base import Tool as L2Tool
from coderking_coding_agent.tools.base import ToolResult as L2ToolResult
from coderking_coding_agent.tools.edit import EditFileTool as L2Edit
from coderking_coding_agent.tools.edit import apply_string_replace as l2_apply
from coderking_coding_agent.tools.file import ReadFileTool as L2Read
from coderking_coding_agent.tools.file import WriteFileTool as L2Write
from coderking_coding_agent.tools.file import invalidate_bytecode as l2_invalidate
from coderking_coding_agent.tools.read import format_numbered_lines as l2_format
from coderking_coding_agent.tools.read import read_path as l2_read_path
from coderking_coding_agent.workspace import SKIP_DIRS as L2_SKIP
from coderking_coding_agent.workspace import ensure_inside as l2_ensure
from coderking_coding_agent.workspace import iter_files as l2_iter


def test_facade_reexports_l2_tool_types() -> None:
    assert Tool is L2Tool
    assert ToolResult is L2ToolResult
    assert EditFileTool is L2Edit
    assert apply_string_replace is l2_apply
    assert ReadFileTool is L2Read
    assert WriteFileTool is L2Write
    assert invalidate_bytecode is l2_invalidate
    assert format_numbered_lines is l2_format
    assert read_path is l2_read_path
    assert ensure_inside is l2_ensure
    assert iter_files is l2_iter
    assert SKIP_DIRS is L2_SKIP
