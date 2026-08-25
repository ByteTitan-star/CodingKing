from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from coderking.tools.base import Tool, ToolResult


async def _git(workspace: Path, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(workspace),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    text = (out + err).decode("utf-8", errors="replace")
    return proc.returncode or 0, text


class GitTool(Tool):
    def __init__(self, workspace: Path, *, name: str, description: str, parameters: dict[str, Any]):
        self.workspace = workspace
        self.name = name
        self.description = description
        self.parameters = parameters


class GitStatusTool(GitTool):
    def __init__(self, workspace: Path):
        super().__init__(
            workspace,
            name="git_status",
            description="git status --short",
            parameters={"type": "object", "properties": {}},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        code, text = await _git(self.workspace, "status", "--short")
        return ToolResult(code == 0, text or "(clean)")


class GitDiffTool(GitTool):
    def __init__(self, workspace: Path):
        super().__init__(
            workspace,
            name="git_diff",
            description="Show unstaged and staged diffs.",
            parameters={"type": "object", "properties": {}},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        _, unstaged = await _git(self.workspace, "diff")
        _, staged = await _git(self.workspace, "diff", "--cached")
        text = "\n".join(p for p in (unstaged, staged) if p).strip()
        return ToolResult(True, text or "(no diff)")


class GitApplyPatchTool(GitTool):
    def __init__(self, workspace: Path):
        super().__init__(
            workspace,
            name="git_apply_patch",
            description="Apply a unified diff with git apply.",
            parameters={
                "type": "object",
                "properties": {"patch": {"type": "string"}},
                "required": ["patch"],
            },
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        patch_file = self.workspace / ".coderking" / "incoming.patch"
        patch_file.parent.mkdir(parents=True, exist_ok=True)
        patch_file.write_text(str(kwargs["patch"]), encoding="utf-8")
        code, text = await _git(self.workspace, "apply", str(patch_file))
        return ToolResult(code == 0, text or "applied")


class GitCommitTool(GitTool):
    requires_approval = True

    def __init__(self, workspace: Path, *, allowed: bool):
        super().__init__(
            workspace,
            name="git_commit",
            description="Create a git commit. Disabled unless allow_commit is set.",
            parameters={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        )
        self.allowed = allowed

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self.allowed:
            return ToolResult(
                False, "git_commit disabled; pass --commit or CODERKING_ALLOW_COMMIT=true"
            )
        msg = str(kwargs["message"])
        await _git(self.workspace, "add", "-A")
        code, text = await _git(self.workspace, "commit", "-m", msg)
        return ToolResult(code == 0, text)
