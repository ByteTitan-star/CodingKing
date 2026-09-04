"""Tool registry: Pi-style atomic coding tools only."""

from __future__ import annotations

from pathlib import Path

from coderking.config import Settings
from coderking.sandbox.base import Sandbox
from coderking.tools.base import Tool
from coderking.tools.edit import EditFileTool
from coderking.tools.file import ReadFileTool, WriteFileTool
from coderking.tools.shell import ShellTool

ATOMIC_TOOL_NAMES = frozenset({"read", "write", "edit", "bash"})


def build_atomic_tools(workspace: Path, sandbox: Sandbox, settings: Settings) -> dict[str, Tool]:
    """Pi-style four atomic tools (Read / Write / Edit / Bash)."""
    tools: list[Tool] = [
        ReadFileTool(workspace, name="read", description="Read a UTF-8 text file."),
        WriteFileTool(
            workspace, name="write", description="Create or overwrite a UTF-8 text file."
        ),
        EditFileTool(workspace, name="edit"),
        ShellTool(sandbox, settings.sandbox_timeout_sec, name="bash"),
    ]
    return {tool.name: tool for tool in tools}


def build_tools(workspace: Path, sandbox: Sandbox, settings: Settings) -> dict[str, Tool]:
    """Return the coding-agent toolset (always atomic)."""
    return build_atomic_tools(workspace, sandbox, settings)
