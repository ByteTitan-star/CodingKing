"""Tool registry: Pi atomic (4) vs SWE extension (legacy harness)."""

from __future__ import annotations

from pathlib import Path

from coderking.config import Settings
from coderking.sandbox.base import Sandbox
from coderking.tools.base import Tool
from coderking.tools.edit import EditFileTool
from coderking.tools.file import DeleteFileTool, ReadFileTool, SearchCodeTool, WriteFileTool
from coderking.tools.git import GitApplyPatchTool, GitCommitTool, GitDiffTool, GitStatusTool
from coderking.tools.meta import meta_tools
from coderking.tools.shell import ShellTool
from coderking.tools.test import RunTestsTool

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


def build_swe_tools(workspace: Path, sandbox: Sandbox, settings: Settings) -> dict[str, Tool]:
    """Legacy 5-role SWE harness toolset (Phase 1 compatibility)."""
    tools: list[Tool] = [
        ReadFileTool(workspace),
        WriteFileTool(workspace),
        WriteFileTool(
            workspace,
            name="create_file",
            description="Create a new UTF-8 text file (same as write_file).",
        ),
        EditFileTool(workspace),
        DeleteFileTool(workspace),
        SearchCodeTool(workspace),
        ShellTool(sandbox, settings.sandbox_timeout_sec),
        RunTestsTool(sandbox, settings.sandbox_timeout_sec),
        GitStatusTool(workspace),
        GitDiffTool(workspace),
        GitApplyPatchTool(workspace),
        GitCommitTool(workspace, allowed=settings.allow_commit),
        *meta_tools(),
    ]
    return {tool.name: tool for tool in tools}


def build_tools(workspace: Path, sandbox: Sandbox, settings: Settings) -> dict[str, Tool]:
    """Return atomic tools unless settings.extension is swe (legacy harness)."""
    if settings.extension == "swe":
        return build_swe_tools(workspace, sandbox, settings)
    return build_atomic_tools(workspace, sandbox, settings)
