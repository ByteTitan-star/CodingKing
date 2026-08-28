from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from coderking_coding_agent.tools.base import Tool, ToolResult
from coderking_coding_agent.tools.read import read_path
from coderking_coding_agent.workspace import ensure_inside, iter_files

_OBJ = {"type": "object"}


def invalidate_bytecode(path: Path) -> None:
    """Drop stale __pycache__ entries for a rewritten source file.

    CPython validates cached bytecode by (source mtime in whole seconds, size).
    When a file is rewritten within the same second at the same size, the stale
    .pyc stays "valid" and subsequent test runs import outdated bytecode.
    """
    if path.suffix != ".py":
        return
    cache_dir = path.parent / "__pycache__"
    if not cache_dir.is_dir():
        return
    stem = path.stem
    for cached in cache_dir.glob(f"{stem}.*.pyc"):
        try:
            cached.unlink()
        except OSError:
            pass


class FileTool(Tool):
    def __init__(self, workspace: Path, *, name: str, description: str, parameters: dict[str, Any]):
        self.workspace = workspace
        self.name = name
        self.description = description
        self.parameters = parameters

    def _resolve(self, path: str) -> Path:
        return ensure_inside(self.workspace, Path(path))


class ReadFileTool(FileTool):
    def __init__(
        self,
        workspace: Path,
        *,
        name: str = "read_file",
        description: str | None = None,
    ):
        super().__init__(
            workspace,
            name=name,
            description=description
            or "Read UTF-8 text, directory globs, or image files with line numbers.",
            parameters={
                **_OBJ,
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "glob": {"type": "string"},
                },
                "required": ["path"],
            },
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        rel = str(kwargs["path"]).replace("\\", "/")
        offset = int(kwargs.get("offset") or 1)
        limit = int(kwargs.get("limit") or 2000)
        glob = kwargs.get("glob")
        glob_str = str(glob) if glob is not None else None
        ok, output = read_path(
            self.workspace,
            rel,
            offset=offset,
            limit=limit,
            glob=glob_str,
        )
        return ToolResult(ok, output)


class WriteFileTool(FileTool):
    def __init__(
        self, workspace: Path, *, name: str = "write_file", description: str | None = None
    ):
        super().__init__(
            workspace,
            name=name,
            description=description or "Create or overwrite a UTF-8 text file.",
            parameters={
                **_OBJ,
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        rel = str(kwargs["path"]).replace("\\", "/")
        path = self._resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(kwargs["content"]), encoding="utf-8")
        invalidate_bytecode(path)
        return ToolResult(True, f"wrote {rel}", changed_file=rel, action="modified")


class DeleteFileTool(FileTool):
    requires_approval = True

    def __init__(self, workspace: Path):
        super().__init__(
            workspace,
            name="delete_file",
            description="Delete a file. Requires human approval.",
            parameters={
                **_OBJ,
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        rel = str(kwargs["path"]).replace("\\", "/")
        path = self._resolve(rel)
        if not path.is_file():
            return ToolResult(False, f"not found: {rel}")
        invalidate_bytecode(path)
        path.unlink()
        return ToolResult(True, f"deleted {rel}", changed_file=rel, action="deleted")


class SearchCodeTool(FileTool):
    def __init__(self, workspace: Path):
        super().__init__(
            workspace,
            name="search_code",
            description="Regex search over workspace text files.",
            parameters={
                **_OBJ,
                "properties": {
                    "pattern": {"type": "string"},
                    "glob": {"type": "string"},
                },
                "required": ["pattern"],
            },
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        pattern = re.compile(str(kwargs["pattern"]))
        glob = str(kwargs.get("glob") or "*")
        hits: list[str] = []
        for path in iter_files(self.workspace):
            if glob != "*" and not path.match(glob):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    rel = path.relative_to(self.workspace.resolve()).as_posix()
                    hits.append(f"{rel}:{i}:{line[:200]}")
                    if len(hits) >= 80:
                        return ToolResult(True, "\n".join(hits))
        return ToolResult(True, "\n".join(hits) if hits else "no matches")
