"""Recoverable per-file checkpoints for mutating coding tools."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from coderking_coding_agent.workspace import ensure_inside

MUTATING_FILE_TOOLS = frozenset(
    {"write", "edit", "write_file", "edit_file", "create_file", "delete_file"}
)
DEFAULT_MAX_CHECKPOINT_BYTES = 10_000_000
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_id(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError(f"invalid {label}")
    return normalized


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _capture(path: Path, *, max_bytes: int) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "recoverable": True, "size": 0, "sha256": None}
    if not path.is_file():
        return {
            "exists": True,
            "recoverable": False,
            "size": 0,
            "sha256": None,
            "reason": "target is not a regular file",
        }
    file_stat = path.stat()
    size = file_stat.st_size
    if size > max_bytes:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return {
            "exists": True,
            "recoverable": False,
            "size": size,
            "sha256": digest.hexdigest(),
            "mode": stat.S_IMODE(file_stat.st_mode),
            "reason": f"file exceeds checkpoint limit of {max_bytes} bytes",
        }
    raw = path.read_bytes()
    return {
        "exists": True,
        "recoverable": True,
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mode": stat.S_IMODE(file_stat.st_mode),
        "content_base64": base64.b64encode(raw).decode("ascii"),
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _atomic_bytes(path: Path, content: bytes, *, mode: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            temp.chmod(mode)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _matches_snapshot(path: Path, expected: dict[str, Any], *, max_bytes: int) -> bool:
    current = _capture(path, max_bytes=max_bytes)
    if bool(current.get("exists")) != bool(expected.get("exists")):
        return False
    if not current.get("exists"):
        return True
    return (
        current.get("recoverable") == expected.get("recoverable")
        and current.get("size") == expected.get("size")
        and current.get("sha256") == expected.get("sha256")
    )


@dataclass(frozen=True)
class PreparedCheckpoint:
    checkpoint_id: str
    path: str
    recoverable: bool
    reason: str | None = None


class CheckpointStore:
    """Persist a prepared → applied/failed → accepted/rolled_back state machine."""

    def __init__(
        self,
        metadata_workspace: Path,
        execution_workspace: Path,
        task_id: str,
        *,
        max_file_bytes: int = DEFAULT_MAX_CHECKPOINT_BYTES,
    ) -> None:
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        self.metadata_workspace = metadata_workspace.resolve()
        self.execution_workspace = execution_workspace.resolve()
        self.task_id = _validate_id(task_id, label="task id")
        self.max_file_bytes = max_file_bytes
        self.directory = self.metadata_workspace / ".coderking" / "checkpoints" / self.task_id

    def prepare(
        self,
        *,
        turn_id: str | None,
        tool_call_id: str | None,
        tool: str,
        arguments: dict[str, Any],
    ) -> PreparedCheckpoint | None:
        if tool not in MUTATING_FILE_TOOLS:
            return None
        rel = str(arguments.get("path") or "").replace("\\", "/").strip()
        if not rel:
            raise ValueError(f"{tool} checkpoint requires a path")
        target = ensure_inside(self.execution_workspace, Path(rel))
        before = _capture(target, max_bytes=self.max_file_bytes)
        checkpoint_id = f"cp_{uuid4().hex[:16]}"
        payload = {
            "schema_version": 1,
            "checkpoint_id": checkpoint_id,
            "task_id": self.task_id,
            "turn_id": turn_id,
            "tool_call_id": tool_call_id,
            "tool": tool,
            "path": target.relative_to(self.execution_workspace).as_posix(),
            "status": "prepared",
            "created_at": _now(),
            "updated_at": _now(),
            "before": before,
            "after": None,
        }
        _atomic_json(self._path(checkpoint_id), payload)
        return PreparedCheckpoint(
            checkpoint_id=checkpoint_id,
            path=payload["path"],
            recoverable=bool(before.get("recoverable")),
            reason=str(before.get("reason")) if before.get("reason") else None,
        )

    def complete(self, checkpoint_id: str, *, ok: bool) -> dict[str, Any]:
        payload = self.load(checkpoint_id)
        if payload.get("status") != "prepared":
            raise ValueError(f"checkpoint is already {payload.get('status')}")
        target = ensure_inside(self.execution_workspace, Path(str(payload["path"])))
        payload["after"] = _capture(target, max_bytes=self.max_file_bytes)
        payload["status"] = "applied" if ok else "failed"
        payload["updated_at"] = _now()
        _atomic_json(self._path(checkpoint_id), payload)
        return payload

    def restore(self, checkpoint_id: str) -> dict[str, Any]:
        payload = self.load(checkpoint_id)
        if payload.get("status") == "accepted":
            raise ValueError("accepted checkpoint cannot be rolled back")
        if payload.get("status") == "rolled_back":
            raise ValueError("checkpoint is already rolled back")
        before = payload.get("before") or {}
        if not before.get("recoverable"):
            raise ValueError(str(before.get("reason") or "checkpoint is not recoverable"))
        target = ensure_inside(self.execution_workspace, Path(str(payload["path"])))
        after = payload.get("after")
        if isinstance(after, dict) and not _matches_snapshot(
            target,
            after,
            max_bytes=self.max_file_bytes,
        ):
            raise ValueError("file changed after checkpoint; refusing to overwrite newer content")
        if before.get("exists"):
            encoded = before.get("content_base64")
            if not isinstance(encoded, str):
                raise ValueError("checkpoint content is missing")
            raw = base64.b64decode(encoded, validate=True)
            mode = before.get("mode")
            _atomic_bytes(target, raw, mode=int(mode) if isinstance(mode, int) else None)
        elif target.is_file():
            target.unlink()
        payload["status"] = "rolled_back"
        payload["updated_at"] = _now()
        _atomic_json(self._path(checkpoint_id), payload)
        return payload

    def accept_all(self) -> int:
        changed = 0
        for payload in self.list():
            if payload.get("status") not in {"prepared", "applied", "failed"}:
                continue
            payload["status"] = "accepted"
            payload["updated_at"] = _now()
            _atomic_json(self._path(str(payload["checkpoint_id"])), payload)
            changed += 1
        return changed

    def mark_all_rolled_back(self) -> int:
        changed = 0
        for payload in self.list():
            if payload.get("status") == "rolled_back":
                continue
            payload["status"] = "rolled_back"
            payload["updated_at"] = _now()
            _atomic_json(self._path(str(payload["checkpoint_id"])), payload)
            changed += 1
        return changed

    def load(self, checkpoint_id: str) -> dict[str, Any]:
        path = self._path(checkpoint_id)
        if not path.is_file():
            raise KeyError(checkpoint_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid checkpoint {checkpoint_id}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("task_id") != self.task_id:
            raise ValueError(f"invalid checkpoint {checkpoint_id}")
        return payload

    def list(self) -> list[dict[str, Any]]:
        if not self.directory.is_dir():
            return []
        items: list[dict[str, Any]] = []
        for path in self.directory.glob("cp_*.json"):
            try:
                payload = self.load(path.stem)
            except (KeyError, ValueError):
                continue
            items.append(payload)
        items.sort(key=lambda item: str(item.get("created_at") or ""))
        return items

    def _path(self, checkpoint_id: str) -> Path:
        checkpoint_id = _validate_id(checkpoint_id, label="checkpoint id")
        return self.directory / f"{checkpoint_id}.json"
