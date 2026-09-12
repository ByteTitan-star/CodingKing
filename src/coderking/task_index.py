"""Derived SQLite index for task lookup, leases, and event cursors."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ACTIVE_STATUSES = frozenset({"pending", "running", "cancelling", "waiting_approval"})


class TaskIndex:
    """Queryable cache; JSON task records remain the portable source of truth."""

    _UPSERT_SQL = """
        INSERT INTO tasks (
            task_id, parent_run_id, session_id, prompt, status, role, workspace,
            iteration, event_cursor, token_input, token_output, pid, lease_owner,
            lease_expires_at, created_at, updated_at, finished_at
        ) VALUES (
            :task_id, :parent_run_id, :session_id, :prompt, :status, :role, :workspace,
            :iteration, :event_cursor, :token_input, :token_output, :pid, :lease_owner,
            :lease_expires_at, :created_at, :updated_at, :finished_at
        )
        ON CONFLICT(task_id) DO UPDATE SET
            parent_run_id=excluded.parent_run_id,
            session_id=excluded.session_id,
            prompt=excluded.prompt,
            status=excluded.status,
            role=excluded.role,
            workspace=excluded.workspace,
            iteration=excluded.iteration,
            event_cursor=excluded.event_cursor,
            token_input=excluded.token_input,
            token_output=excluded.token_output,
            pid=excluded.pid,
            lease_owner=excluded.lease_owner,
            lease_expires_at=excluded.lease_expires_at,
            created_at=excluded.created_at,
            updated_at=excluded.updated_at,
            finished_at=excluded.finished_at
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    parent_run_id TEXT,
                    session_id TEXT,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    role TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    iteration INTEGER NOT NULL DEFAULT 0,
                    event_cursor INTEGER NOT NULL DEFAULT 0,
                    token_input INTEGER NOT NULL DEFAULT 0,
                    token_output INTEGER NOT NULL DEFAULT 0,
                    pid INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, updated_at DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _record_values(
        record: Mapping[str, Any],
        *,
        lease_ttl_sec: float,
        now: float | None = None,
    ) -> dict[str, Any]:
        if lease_ttl_sec <= 0:
            raise ValueError("lease_ttl_sec must be positive")
        status = str(record.get("status") or "pending")
        pid = int(record.get("pid") or 0)
        active = status in ACTIVE_STATUSES
        lease_owner = f"pid:{pid}" if active and pid > 0 else None
        lease_expires_at = (time.time() if now is None else now) + lease_ttl_sec
        return {
            "task_id": str(record["task_id"]),
            "parent_run_id": record.get("parent_run_id"),
            "session_id": record.get("session_id"),
            "prompt": str(record.get("prompt") or ""),
            "status": status,
            "role": str(record.get("role") or "planner"),
            "workspace": str(record.get("workspace") or ""),
            "iteration": int(record.get("iteration") or 0),
            "event_cursor": int(record.get("event_cursor") or 0),
            "token_input": int(record.get("token_input") or 0),
            "token_output": int(record.get("token_output") or 0),
            "pid": pid,
            "lease_owner": lease_owner,
            "lease_expires_at": lease_expires_at if lease_owner else None,
            "created_at": str(record.get("created_at") or ""),
            "updated_at": str(record.get("updated_at") or ""),
            "finished_at": record.get("finished_at"),
        }

    def upsert(self, record: Mapping[str, Any], *, lease_ttl_sec: float = 60.0) -> None:
        values = self._record_values(record, lease_ttl_sec=lease_ttl_sec)
        with self._connect() as connection:
            connection.execute(self._UPSERT_SQL, values)

    def replace_all(
        self,
        records: list[Mapping[str, Any]],
        *,
        lease_ttl_sec: float = 60.0,
    ) -> None:
        """Atomically replace this derived index from canonical records."""
        if lease_ttl_sec <= 0:
            raise ValueError("lease_ttl_sec must be positive")
        current = time.time()
        values = [
            self._record_values(record, lease_ttl_sec=lease_ttl_sec, now=current)
            for record in records
        ]
        with self._connect() as connection:
            connection.execute("DELETE FROM tasks")
            connection.executemany(self._UPSERT_SQL, values)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return dict(row) if row is not None else None

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()
        return int(row["count"]) if row is not None else 0

    def list(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        query = "SELECT * FROM tasks"
        parameters: list[Any] = []
        if status is not None:
            query += " WHERE status = ?"
            parameters.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def acquire_lease(
        self,
        task_id: str,
        owner: str,
        *,
        ttl_sec: float = 60.0,
        now: float | None = None,
    ) -> bool:
        if ttl_sec <= 0:
            raise ValueError("ttl_sec must be positive")
        if not owner:
            raise ValueError("owner must not be empty")
        current = time.time() if now is None else now
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET lease_owner = ?, lease_expires_at = ?
                WHERE task_id = ?
                  AND (lease_owner IS NULL OR lease_owner = ? OR lease_expires_at <= ?)
                """,
                (owner, current + ttl_sec, task_id, owner, current),
            )
        return cursor.rowcount == 1

    def renew_lease(
        self,
        task_id: str,
        owner: str,
        *,
        ttl_sec: float = 60.0,
        now: float | None = None,
    ) -> bool:
        if ttl_sec <= 0:
            raise ValueError("ttl_sec must be positive")
        if not owner:
            raise ValueError("owner must not be empty")
        current = time.time() if now is None else now
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks SET lease_expires_at = ?
                WHERE task_id = ? AND lease_owner = ?
                """,
                (current + ttl_sec, task_id, owner),
            )
        return cursor.rowcount == 1

    def release_lease(self, task_id: str, owner: str) -> bool:
        if not owner:
            raise ValueError("owner must not be empty")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks SET lease_owner = NULL, lease_expires_at = NULL
                WHERE task_id = ? AND lease_owner = ?
                """,
                (task_id, owner),
            )
        return cursor.rowcount == 1
