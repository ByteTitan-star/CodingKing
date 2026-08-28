"""Facade re-export (#23)."""

from __future__ import annotations

from coderking_coding_agent.sandbox.cow import (
    CowWorkspace,
    SnapshotRecord,
    WorkspaceSnapshot,
    clone_workspace,
    cow_root,
)

__all__ = [
    "CowWorkspace",
    "SnapshotRecord",
    "WorkspaceSnapshot",
    "clone_workspace",
    "cow_root",
]
