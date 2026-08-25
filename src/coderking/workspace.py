from __future__ import annotations

from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".coderking",
    "dist",
    "build",
    ".ruff_cache",
    ".pytest_cache",
}


def ensure_inside(workspace: Path, target: Path) -> Path:
    root = workspace.resolve()
    resolved = (root / target).resolve() if not target.is_absolute() else target.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"path escapes workspace: {target}") from exc
    return resolved


def iter_files(workspace: Path, *, max_files: int = 400) -> list[Path]:
    root = workspace.resolve()
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
        if len(files) >= max_files:
            break
    return files
