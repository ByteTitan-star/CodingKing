"""Copy-on-Write workspace isolation for sandbox tasks."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from coderking.diffing import restore_snapshot, snapshot_workspace, unified_diff
from coderking.workspace import SKIP_DIRS

SnapshotId = str


@dataclass(frozen=True)
class SnapshotRecord:
    id: SnapshotId
    path: Path


class WorkspaceSnapshot(Protocol):
    async def commit(self) -> SnapshotId: ...

    async def rollback(self, snapshot_id: SnapshotId) -> None: ...

    async def diff(self, snapshot_id: SnapshotId) -> str: ...


def cow_root(source: Path) -> Path:
    return source.resolve() / ".coderking" / "cow"


def _ignore_names(_dir: str, names: list[str]) -> set[str]:
    return {name for name in names if name in SKIP_DIRS}


def _link_or_copy(src: str, dst: str) -> None:
    # Full file copy — hardlinks would share inodes and leak edits into source.
    shutil.copy2(src, dst)


def clone_workspace(source: Path, dest: Path) -> None:
    """Clone source into dest, skipping SKIP_DIRS and secret paths."""
    from coderking.sandbox.credentials import secret_ignore_names

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, ignore=secret_ignore_names, copy_function=_link_or_copy)


class CowWorkspace:
    """Ephemeral task workspace under `.coderking/cow/{session_id}/work`.

    Docker / tools operate on ``work_path``. The original ``source`` stays
    untouched until ``promote()``. Snapshots are content-based for fast rollback.
    """

    def __init__(self, source: Path, *, session_id: str | None = None) -> None:
        self.source = source.resolve()
        self.session_id = session_id or uuid4().hex[:12]
        self.base_dir = cow_root(self.source) / self.session_id
        self.work_path = self.base_dir / "work"
        self._snapshots_dir = self.base_dir / "snapshots"
        self._snapshots: dict[SnapshotId, Path] = {}
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def materialize(self) -> Path:
        """Create the isolated work tree and return its path."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        clone_workspace(self.source, self.work_path)
        self._active = True
        return self.work_path

    async def commit(self) -> SnapshotId:
        if not self._active:
            raise RuntimeError("CowWorkspace is not materialized")
        snap_id = uuid4().hex[:12]
        payload = snapshot_workspace(self.work_path)
        path = self._snapshots_dir / f"{snap_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self._snapshots[snap_id] = path
        return snap_id

    async def rollback(self, snapshot_id: SnapshotId) -> None:
        payload = self._load_snapshot(snapshot_id)
        restore_snapshot(self.work_path, payload)

    async def diff(self, snapshot_id: SnapshotId) -> str:
        payload = self._load_snapshot(snapshot_id)
        return unified_diff(self.work_path, payload)

    def promote(self) -> None:
        """Copy work tree changes back onto the source workspace."""
        if not self._active:
            return
        for path in self.work_path.rglob("*"):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(self.work_path).parts
            if any(part in SKIP_DIRS for part in rel_parts):
                continue
            rel = path.relative_to(self.work_path)
            dest = self.source / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        # Delete files removed in the overlay (present in source, absent in work)
        source_files = {
            p.relative_to(self.source).as_posix()
            for p in self.source.rglob("*")
            if p.is_file()
            and not any(part in SKIP_DIRS for part in p.relative_to(self.source).parts)
        }
        work_files = {
            p.relative_to(self.work_path).as_posix()
            for p in self.work_path.rglob("*")
            if p.is_file()
            and not any(part in SKIP_DIRS for part in p.relative_to(self.work_path).parts)
        }
        for rel in source_files - work_files:
            target = self.source / rel
            if target.is_file():
                target.unlink()

    def close(self) -> None:
        self._active = False
        if self.base_dir.exists():
            shutil.rmtree(self.base_dir, ignore_errors=True)

    def _load_snapshot(self, snapshot_id: SnapshotId) -> dict[str, str | None]:
        path = self._snapshots.get(snapshot_id) or (self._snapshots_dir / f"{snapshot_id}.json")
        if not path.is_file():
            raise KeyError(f"unknown snapshot: {snapshot_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("invalid snapshot payload")
        return data
