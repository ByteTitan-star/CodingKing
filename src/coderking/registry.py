from __future__ import annotations

import json
import time
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


@dataclass
class SessionMeta:
    """Summary of one saved session, for listing and resume pickers."""

    session_id: str
    updated_at: str
    prompt: str
    nodes: int
    token_input: int
    token_output: int


def new_session_id(workspace: Path) -> str:
    """Timestamped, sortable session id; suffixed when created within the same second."""
    base = time.strftime("s-%Y%m%d-%H%M%S")
    sessions_dir = _dir(workspace) / "sessions"
    sid = base
    n = 2
    while (sessions_dir / f"{sid}.jsonl").is_file() or (sessions_dir / f"{sid}.head").is_file():
        sid = f"{base}-{n}"
        n += 1
    return sid


def current_session_id(workspace: Path) -> str:
    path = _dir(workspace) / "session.current"
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    return "default"


def set_current_session_id(workspace: Path, session_id: str) -> None:
    path = _dir(workspace) / "session.current"
    path.write_text(f"{session_id}\n", encoding="utf-8")


def _scan_session_file(path: Path, session_id: str) -> SessionMeta | None:
    nodes = 0
    prompt = ""
    updated_at = ""
    token_input = 0
    token_output = 0
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError:
                    continue  # tolerate corrupt tails; recover_tail will fix them
                nodes += 1
                created = data.get("created_at")
                if isinstance(created, str) and created:
                    updated_at = created
                payload = data.get("payload") or {}
                snapshot = payload.get("session_snapshot")
                if isinstance(snapshot, dict):
                    if snapshot.get("prompt"):
                        prompt = str(snapshot["prompt"])
                    token_input = int(snapshot.get("token_input") or token_input)
                    token_output = int(snapshot.get("token_output") or token_output)
    except OSError:
        return None
    if nodes == 0:
        return None
    return SessionMeta(
        session_id=session_id,
        updated_at=updated_at or "—",
        prompt=prompt,
        nodes=nodes,
        token_input=token_input,
        token_output=token_output,
    )


def list_sessions(workspace: Path) -> list[SessionMeta]:
    """All saved sessions for the workspace, newest first."""
    sessions_dir = _dir(workspace) / "sessions"
    if not sessions_dir.is_dir():
        return []
    metas: list[SessionMeta] = []
    for jsonl in sorted(sessions_dir.glob("*.jsonl")):
        meta = _scan_session_file(jsonl, jsonl.stem)
        if meta is not None:
            metas.append(meta)
    metas.sort(key=lambda m: m.updated_at, reverse=True)
    return metas


def session_jsonl_path(workspace: Path, session_id: str = "default") -> Path:
    return _dir(workspace) / "sessions" / f"{session_id}.jsonl"


def _session_repo(workspace: Path, session_id: str = "default"):
    from coderking_coding_agent.session import SessionRepo

    return SessionRepo(workspace, session_id=session_id)


def load_session(workspace: Path, session_id: str | None = None) -> dict[str, Any]:
    sid = session_id or current_session_id(workspace)
    jsonl = session_jsonl_path(workspace, sid)
    if jsonl.is_file():
        return _session_repo(workspace, sid).materialize_session_state()
    if sid != "default":
        return {}
    path = session_path(workspace)
    if not path.is_file():
        return {}
    from coderking_coding_agent.session import import_legacy_session

    repo = import_legacy_session(workspace)
    if repo is None:
        return {}
    return repo.materialize_session_state()


def save_session(workspace: Path, payload: dict[str, Any], session_id: str | None = None) -> None:
    sid = session_id or current_session_id(workspace)
    repo = _session_repo(workspace, sid)
    repo.append("message", {"session_snapshot": payload})


def ensure_session(workspace: Path, session_id: str | None = None) -> str:
    """Materialize the session file (root node) so it shows up in listings."""
    sid = session_id or current_session_id(workspace)
    _session_repo(workspace, sid)
    return sid
