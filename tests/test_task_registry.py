from __future__ import annotations

import json
from pathlib import Path

from coderking.registry import list_tasks, load_current, persist_state
from coderking.runtime.state import AgentState, TaskStatus


def test_stale_running_task_recovers_as_interrupted(tmp_path: Path) -> None:
    state = AgentState(task="work", repository=str(tmp_path), task_id="stale-task")
    state.status = TaskStatus.RUNNING
    persist_state(tmp_path, state)

    task_path = tmp_path / ".coderking" / "tasks" / "stale-task.json"
    current_path = tmp_path / ".coderking" / "current_task.json"
    for path in (task_path, current_path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["pid"] = 999_999_999
        path.write_text(json.dumps(payload), encoding="utf-8")

    records = list_tasks(tmp_path)

    assert records[0].status == "interrupted"
    assert records[0].finished_at
    assert "process exited" in " ".join(records[0].errors or [])
    assert load_current(tmp_path).status == "interrupted"  # type: ignore[union-attr]


def test_task_record_reader_ignores_future_fields(tmp_path: Path) -> None:
    state = AgentState(task="done", repository=str(tmp_path), task_id="future-task")
    state.status = TaskStatus.SUCCEEDED
    persist_state(tmp_path, state)
    path = tmp_path / ".coderking" / "tasks" / "future-task.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["future_schema_field"] = {"v": 2}
    path.write_text(json.dumps(payload), encoding="utf-8")

    records = list_tasks(tmp_path)

    assert records[0].task_id == "future-task"
