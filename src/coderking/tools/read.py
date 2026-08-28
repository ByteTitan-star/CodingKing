"""Pi-style read tool: line numbers, offset/limit, directory glob, image blocks."""

from __future__ import annotations

import base64
import json
from pathlib import Path

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
MAX_DIR_FILES = 50
MAX_LINES_PER_FILE = 500
MAX_TOTAL_BYTES = 100_000

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def format_numbered_lines(lines: list[str], *, offset: int = 1) -> str:
    return "\n".join(f"{idx}|{line}" for idx, line in enumerate(lines, start=offset))


def read_path(
    workspace: Path,
    rel_path: str,
    *,
    offset: int = 1,
    limit: int = 2000,
    glob: str | None = None,
) -> tuple[bool, str]:
    from coderking.workspace import ensure_inside

    root = workspace.resolve()
    target = ensure_inside(root, Path(rel_path.replace("\\", "/")))
    if target.is_dir():
        return _read_directory(target, root, offset=offset, limit=limit, glob=glob)
    if not target.is_file():
        return False, f"not found: {rel_path}"
    return _read_file(target, offset=offset, limit=limit)


def _read_file(path: Path, *, offset: int, limit: int) -> tuple[bool, str]:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        data = path.read_bytes()
        payload = {
            "type": "image",
            "mime": _MIME_BY_SUFFIX[suffix],
            "path": path.name,
            "base64": base64.b64encode(data).decode("ascii"),
        }
        return True, json.dumps(payload, ensure_ascii=False)

    try:
        lines = _iter_text_lines(path, offset=offset, limit=limit)
    except UnicodeDecodeError:
        return False, "binary file not supported; use bash `file` to inspect"
    if "\x00" in "".join(lines):
        return False, "binary file not supported; use bash `file` to inspect"
    numbered = format_numbered_lines(lines, offset=offset)
    if len(numbered) > MAX_TOTAL_BYTES:
        numbered = numbered[:MAX_TOTAL_BYTES] + "\n...[truncated]"
    return True, numbered


def _iter_text_lines(path: Path, *, offset: int, limit: int) -> list[str]:
    if offset < 1:
        raise ValueError("offset must be >= 1")
    if limit < 1:
        return []
    collected: list[str] = []
    with path.open("r", encoding="utf-8", errors="strict") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if line_no < offset:
                continue
            if len(collected) >= limit:
                break
            collected.append(raw.rstrip("\n\r"))
    return collected


def _read_directory(
    directory: Path,
    workspace: Path,
    *,
    offset: int,
    limit: int,
    glob: str | None,
) -> tuple[bool, str]:
    pattern = glob or "*"
    candidates = sorted(directory.glob(pattern))[:MAX_DIR_FILES]
    if not candidates:
        return False, f"no files match glob {pattern!r} under {directory.name}"
    chunks: list[str] = []
    total = 0
    for file_path in candidates:
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(workspace).as_posix()
        per_file_limit = min(limit, MAX_LINES_PER_FILE)
        ok, body = _read_file(file_path, offset=offset, limit=per_file_limit)
        if not ok:
            body = f"(skipped: {body})"
        header = f"=== {rel} ===\n"
        piece = header + body
        if total + len(piece) > MAX_TOTAL_BYTES:
            chunks.append("...[directory read truncated at 100KB]")
            break
        chunks.append(piece)
        total += len(piece)
    return True, "\n\n".join(chunks)
