from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from coderking.runtime.state import AgentState


@dataclass
class TaskRecord:
    task_id: str
    prompt: str
    status: str
    role: str
    iteration: int
    changed_files: list[str]
    test_results: str
    token_input: int
    token_output: int
    workspace: str
    last_test_ok: bool | None
    repair_count: int


def _dir(workspace: Path) -> Path:
    path = workspace.resolve() / ".coderking"
    path.mkdir(parents=True, exist_ok=True)
    (path / "cancels").mkdir(exist_ok=True)
    return path


def record_from_state(state: AgentState, workspace: Path) -> TaskRecord:
    return TaskRecord(
        task_id=state.task_id,
        prompt=state.task,
        status=state.status.value,
        role=state.role.value,
        iteration=state.iteration,
        changed_files=list(state.changed_files),
        test_results=state.test_results,
        token_input=state.token_input,
        token_output=state.token_output,
        workspace=str(workspace.resolve()),
        last_test_ok=state.last_test_ok,
        repair_count=state.repair_count,
    )


def save_record(workspace: Path, record: TaskRecord) -> None:
    path = _dir(workspace) / "current_task.json"
    path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8")
    (_dir(workspace) / "tasks").mkdir(exist_ok=True)
    (_dir(workspace) / "tasks" / f"{record.task_id}.json").write_text(
        json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_current(workspace: Path) -> TaskRecord | None:
    path = _dir(workspace) / "current_task.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return TaskRecord(**data)


def load_task(workspace: Path, task_id: str) -> TaskRecord | None:
    path = _dir(workspace) / "tasks" / f"{task_id}.json"
    if not path.is_file():
        current = load_current(workspace)
        if current and current.task_id == task_id:
            return current
        return None
    return TaskRecord(**json.loads(path.read_text(encoding="utf-8")))


def request_cancel(workspace: Path, task_id: str) -> None:
    (_dir(workspace) / "cancels" / task_id).write_text("1", encoding="utf-8")


def cancel_requested(workspace: Path, task_id: str) -> bool:
    return (_dir(workspace) / "cancels" / task_id).is_file()


def clear_cancel(workspace: Path, task_id: str) -> None:
    path = _dir(workspace) / "cancels" / task_id
    if path.exists():
        path.unlink()


def persist_state(workspace: Path, state: AgentState) -> None:
    save_record(workspace, record_from_state(state, workspace))


def session_path(workspace: Path) -> Path:
    return _dir(workspace) / "session.json"


def session_jsonl_path(workspace: Path, session_id: str = "default") -> Path:
    return _dir(workspace) / "sessions" / f"{session_id}.jsonl"


def _session_repo(workspace: Path, session_id: str = "default"):
    from coderking_coding_agent.session import SessionRepo

    return SessionRepo(workspace, session_id=session_id)


def load_session(workspace: Path) -> dict[str, Any]:
    jsonl = session_jsonl_path(workspace)
    if jsonl.is_file():
        return _session_repo(workspace).materialize_session_state()
    path = session_path(workspace)
    if not path.is_file():
        return {}
    from coderking_coding_agent.session import import_legacy_session

    repo = import_legacy_session(workspace)
    if repo is None:
        return {}
    return repo.materialize_session_state()


def save_session(workspace: Path, payload: dict[str, Any]) -> None:
    repo = _session_repo(workspace)
    repo.append("message", {"session_snapshot": payload})
