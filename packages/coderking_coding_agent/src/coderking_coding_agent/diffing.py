from __future__ import annotations

import base64
import difflib
from pathlib import Path

from coderking_coding_agent.workspace import iter_files

_TEXT_PREFIX = "coderking:text:v1:"
_BINARY_PREFIX = "coderking:base64:v1:"
_INCOMPLETE_KEY = "\x00coderking:snapshot:incomplete"
DEFAULT_MAX_SNAPSHOT_FILES = 400
DEFAULT_MAX_FILE_BYTES = 1_000_000


def _encode_content(raw: bytes) -> str:
    try:
        return _TEXT_PREFIX + raw.decode("utf-8")
    except UnicodeDecodeError:
        return _BINARY_PREFIX + base64.b64encode(raw).decode("ascii")


def _decode_content(value: str) -> tuple[bytes, str | None]:
    if value.startswith(_TEXT_PREFIX):
        text = value.removeprefix(_TEXT_PREFIX)
        return text.encode("utf-8"), text
    if value.startswith(_BINARY_PREFIX):
        return base64.b64decode(value.removeprefix(_BINARY_PREFIX)), None
    # Backward compatibility with pre-v1 snapshots, which stored plain text.
    return value.encode("utf-8"), value


def snapshot_workspace(
    workspace: Path,
    *,
    max_files: int = DEFAULT_MAX_SNAPSHOT_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    root = workspace.resolve()
    paths = iter_files(root, max_files=max_files + 1)
    incomplete: list[str] = []
    if len(paths) > max_files:
        incomplete.append(f"more than {max_files} files")
        paths = paths[:max_files]
    for path in paths:
        rel = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
            if len(raw) > max_file_bytes:
                incomplete.append(f"{rel} exceeds {max_file_bytes} bytes")
                continue
            snap[rel] = _encode_content(raw)
        except OSError as exc:
            incomplete.append(f"{rel}: {exc}")
    if incomplete:
        snap[_INCOMPLETE_KEY] = "; ".join(incomplete[:8])
    return snap


def unified_diff(workspace: Path, snapshot: dict[str, str | None]) -> str:
    root = workspace.resolve()
    current: dict[str, str | None] = snapshot_workspace(root)
    baseline_incomplete = snapshot.get(_INCOMPLETE_KEY)
    current_incomplete = current.get(_INCOMPLETE_KEY)
    names = sorted((set(snapshot) | set(current)) - {_INCOMPLETE_KEY})
    chunks: list[str] = []
    if baseline_incomplete or current_incomplete:
        reasons = "; ".join(
            str(reason) for reason in (baseline_incomplete, current_incomplete) if reason
        )
        chunks.append(f"# CoderKing snapshot incomplete: {reasons}\n")
    for name in names:
        old_encoded = snapshot.get(name)
        new_encoded = current.get(name)
        if old_encoded == new_encoded:
            continue
        old_raw, old_text = _decode_content(old_encoded) if old_encoded is not None else (b"", "")
        new_raw, new_text = _decode_content(new_encoded) if new_encoded is not None else (b"", "")
        label_a = "/dev/null" if old_encoded is None else name
        label_b = "/dev/null" if new_encoded is None else name
        if old_text is None or new_text is None:
            if old_raw != new_raw:
                chunks.append(f"Binary files {label_a} and {label_b} differ\n")
            continue
        old_lines = old_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)
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
    if not snapshot:
        raise ValueError("cannot rollback without a captured workspace snapshot")
    if snapshot.get(_INCOMPLETE_KEY):
        raise ValueError(f"cannot rollback an incomplete snapshot: {snapshot[_INCOMPLETE_KEY]}")
    root = workspace.resolve()
    current = snapshot_workspace(root)
    if current.get(_INCOMPLETE_KEY):
        raise ValueError(f"cannot rollback safely: {current[_INCOMPLETE_KEY]}")
    for rel, _content in list(current.items()):
        if rel == _INCOMPLETE_KEY:
            continue
        if rel not in snapshot:
            path = root / rel
            if path.is_file():
                path.unlink()
    for rel, content in snapshot.items():
        if rel == _INCOMPLETE_KEY:
            continue
        path = root / rel
        if content is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        raw, _text = _decode_content(content)
        path.write_bytes(raw)
