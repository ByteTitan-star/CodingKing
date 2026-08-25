from __future__ import annotations

import difflib
from pathlib import Path

from coderking.workspace import iter_files


def snapshot_workspace(workspace: Path, *, max_files: int = 400) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    root = workspace.resolve()
    for path in iter_files(root, max_files=max_files):
        rel = path.relative_to(root).as_posix()
        try:
            snap[rel] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            snap[rel] = None
    return snap


def unified_diff(workspace: Path, snapshot: dict[str, str | None]) -> str:
    root = workspace.resolve()
    current: dict[str, str | None] = snapshot_workspace(root)
    names = sorted(set(snapshot) | set(current))
    chunks: list[str] = []
    for name in names:
        old = snapshot.get(name)
        new = current.get(name)
        if old == new:
            continue
        old_lines = (old or "").splitlines(keepends=True)
        new_lines = (new or "").splitlines(keepends=True)
        label_a = "/dev/null" if old is None else name
        label_b = "/dev/null" if new is None else name
        piece = "".join(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=label_a,
                tofile=label_b,
            )
        )
        if piece:
            chunks.append(piece)
    return "\n".join(chunks)


def restore_snapshot(workspace: Path, snapshot: dict[str, str | None]) -> None:
    root = workspace.resolve()
    current = snapshot_workspace(root)
    for rel, _content in list(current.items()):
        if rel not in snapshot:
            path = root / rel
            if path.is_file():
                path.unlink()
    for rel, content in snapshot.items():
        path = root / rel
        if content is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
