"""Facade re-export of L2 workspace diff helpers (#23)."""

from __future__ import annotations

from coderking_coding_agent.diffing import restore_snapshot, snapshot_workspace, unified_diff

__all__ = ["restore_snapshot", "snapshot_workspace", "unified_diff"]
