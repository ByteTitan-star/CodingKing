from __future__ import annotations

from pathlib import Path

import pytest

from coderking.registry import persist_state, query_task_index, rebuild_task_index
from coderking.runtime.state import AgentState, TaskStatus
from coderking.task_index import TaskIndex


def test_persist_state_updates_sqlite_index_and_releases_terminal_lease(
    tmp_path: Path,
) -> None:
    state = AgentState(task="work", repository=str(tmp_path), task_id="indexed-task")
    state.status = TaskStatus.RUNNING
    state.event_cursor = 7
    persist_state(tmp_path, state)
    index = TaskIndex(tmp_path / ".coderking" / "state.db")

    running = index.get(state.task_id)

    assert running is not None
    assert running["status"] == "running"
    assert running["event_cursor"] == 7
    assert running["lease_owner"] == f"pid:{state.pid}"
    assert running["lease_expires_at"] is not None

    state.status = TaskStatus.SUCCEEDED
    persist_state(tmp_path, state)
    finished = index.get(state.task_id)
    assert finished is not None
    assert finished["status"] == "succeeded"
    assert finished["lease_owner"] is None
    assert finished["lease_expires_at"] is None


def test_task_index_query_filters_status(tmp_path: Path) -> None:
    failed = AgentState(task="failed", repository=str(tmp_path), task_id="failed-index")
    failed.status = TaskStatus.FAILED
    persist_state(tmp_path, failed)
    done = AgentState(task="done", repository=str(tmp_path), task_id="done-index")
    done.status = TaskStatus.SUCCEEDED
    persist_state(tmp_path, done)

    rows = query_task_index(tmp_path, status="failed")

    assert [row["task_id"] for row in rows] == ["failed-index"]


def test_task_index_lease_is_exclusive_and_can_expire(tmp_path: Path) -> None:
    index = TaskIndex(tmp_path / "state.db")
    index.upsert(
        {
            "task_id": "lease-task",
            "prompt": "work",
            "status": "interrupted",
            "role": "coding",
            "workspace": str(tmp_path),
            "created_at": "2026-09-12T00:00:00+00:00",
            "updated_at": "2026-09-12T00:00:00+00:00",
        }
    )

    assert index.acquire_lease("lease-task", "worker-a", ttl_sec=10, now=100)
    assert not index.acquire_lease("lease-task", "worker-b", ttl_sec=10, now=105)
    assert index.acquire_lease("lease-task", "worker-b", ttl_sec=10, now=111)
    assert not index.renew_lease("lease-task", "worker-a", ttl_sec=10, now=112)
    assert index.renew_lease("lease-task", "worker-b", ttl_sec=10, now=112)
    assert index.release_lease("lease-task", "worker-b")


def test_query_bootstraps_index_from_legacy_json_records(tmp_path: Path) -> None:
    state = AgentState(task="legacy", repository=str(tmp_path), task_id="legacy-task")
    state.status = TaskStatus.FAILED
    persist_state(tmp_path, state)
    root = tmp_path / ".coderking"
    for suffix in ("", "-wal", "-shm"):
        path = root / f"state.db{suffix}"
        if path.exists():
            path.unlink()

    rows = query_task_index(tmp_path, status="failed")

    assert [row["task_id"] for row in rows] == ["legacy-task"]


def test_rebuild_removes_rows_without_canonical_json(tmp_path: Path) -> None:
    state = AgentState(task="kept", repository=str(tmp_path), task_id="kept-task")
    state.status = TaskStatus.SUCCEEDED
    persist_state(tmp_path, state)
    index = TaskIndex(tmp_path / ".coderking" / "state.db")
    index.upsert(
        {
            "task_id": "orphan-task",
            "prompt": "orphan",
            "status": "failed",
            "role": "coding",
            "workspace": str(tmp_path),
            "created_at": "2026-09-12T00:00:00+00:00",
            "updated_at": "2026-09-12T00:00:00+00:00",
        }
    )

    assert rebuild_task_index(tmp_path) == 1
    assert index.get("kept-task") is not None
    assert index.get("orphan-task") is None


def test_task_index_validates_lease_arguments(tmp_path: Path) -> None:
    index = TaskIndex(tmp_path / "state.db")
    with pytest.raises(ValueError, match="positive"):
        index.upsert({"task_id": "bad"}, lease_ttl_sec=0)
    with pytest.raises(ValueError, match="empty"):
        index.release_lease("bad", "")
