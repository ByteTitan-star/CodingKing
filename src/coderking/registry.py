from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
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
    context_tokens_estimated: int = 0
    compression_count: int = 0
    micro_compaction_count: int = 0
    session_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    finished_at: str | None = None
    pid: int = 0
    errors: list[str] | None = None


def _dir(workspace: Path) -> Path:
    path = workspace.resolve() / ".coderking"
    path.mkdir(parents=True, exist_ok=True)
    (path / "cancels").mkdir(exist_ok=True)
    return path


def record_from_state(state: AgentState, workspace: Path) -> TaskRecord:
    now = datetime.now(UTC).isoformat()
    state.updated_at = now
    state.pid = os.getpid()
    if state.status.value in {"succeeded", "failed", "interrupted"}:
        state.finished_at = state.finished_at or now
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
        context_tokens_estimated=state.context_tokens_estimated,
        compression_count=state.compression_count,
        micro_compaction_count=state.micro_compaction_count,
        session_id=state.session_id,
        created_at=state.created_at,
        updated_at=state.updated_at,
        finished_at=state.finished_at,
        pid=state.pid,
        errors=list(state.errors),
    )


def _atomic_write_record(path: Path, record: TaskRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(asdict(record), handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def save_record(workspace: Path, record: TaskRecord) -> None:
    path = _dir(workspace) / "current_task.json"
    task_path = _dir(workspace) / "tasks" / f"{record.task_id}.json"
    _atomic_write_record(task_path, record)
    _atomic_write_record(path, record)


def _record_from_data(data: dict[str, Any]) -> TaskRecord:
    allowed = {item.name for item in fields(TaskRecord)}
    filtered = {key: value for key, value in data.items() if key in allowed}
    if filtered.get("errors") is None:
        filtered["errors"] = []
    return TaskRecord(**filtered)


def _read_record(path: Path) -> TaskRecord | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _record_from_data(data)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def recover_stale_tasks(workspace: Path) -> int:
    """Mark orphaned running/waiting records interrupted after process death."""
    root = _dir(workspace)
    paths = list((root / "tasks").glob("*.json")) if (root / "tasks").is_dir() else []
    current_path = root / "current_task.json"
    recovered: dict[str, TaskRecord] = {}
    for path in [*paths, current_path]:
        record = _read_record(path)
        if record is None or record.task_id in recovered:
            continue
        if record.status not in {"running", "cancelling", "waiting_approval"} or _pid_alive(
            record.pid
        ):
            continue
        now = datetime.now(UTC).isoformat()
        record.status = "interrupted"
        record.updated_at = now
        record.finished_at = now
        record.errors = [*(record.errors or []), "agent process exited before task completion"]
        recovered[record.task_id] = record
        _atomic_write_record(root / "tasks" / f"{record.task_id}.json", record)
    current = _read_record(current_path)
    if current is not None and current.task_id in recovered:
        _atomic_write_record(current_path, recovered[current.task_id])
    return len(recovered)


def load_current(workspace: Path) -> TaskRecord | None:
    recover_stale_tasks(workspace)
    path = _dir(workspace) / "current_task.json"
    return _read_record(path)


def load_task(workspace: Path, task_id: str) -> TaskRecord | None:
    recover_stale_tasks(workspace)
    path = _dir(workspace) / "tasks" / f"{task_id}.json"
    if not path.is_file():
        current = load_current(workspace)
        if current and current.task_id == task_id:
            return current
        return None
    return _read_record(path)


def list_tasks(workspace: Path) -> list[TaskRecord]:
    """Return persisted task records, newest file first."""
    recover_stale_tasks(workspace)
    task_dir = _dir(workspace) / "tasks"
    if not task_dir.is_dir():
        return []
    records: list[tuple[int, TaskRecord]] = []
    for path in task_dir.glob("*.json"):
        try:
            record = _read_record(path)
            if record is not None:
                records.append((path.stat().st_mtime_ns, record))
        except OSError:
            continue
    records.sort(key=lambda item: item[0], reverse=True)
    return [record for _, record in records]


def request_cancel(workspace: Path, task_id: str) -> None:
    root = _dir(workspace)
    task_path = root / "tasks" / f"{task_id}.json"
    record = _read_record(task_path)
    if record is not None and record.status in {"succeeded", "failed", "interrupted"}:
        return
    (root / "cancels" / task_id).write_text("1", encoding="utf-8")
    if record is None or record.status not in {"pending", "running", "waiting_approval"}:
        return
    record.status = "cancelling"
    record.updated_at = datetime.now(UTC).isoformat()
    _atomic_write_record(task_path, record)
    current_path = root / "current_task.json"
    current = _read_record(current_path)
    if current is not None and current.task_id == task_id:
        _atomic_write_record(current_path, record)


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
    from coderking_coding_agent.session.repo import validate_session_id

    session_id = validate_session_id(session_id)
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
    from coderking_coding_agent.session.repo import validate_session_id

    session_id = validate_session_id(session_id)
    return _dir(workspace) / "sessions" / f"{session_id}.jsonl"


def _session_repo(workspace: Path, session_id: str = "default"):
    from coderking_coding_agent.session import SessionRepo

    return SessionRepo(workspace, session_id=session_id)


def load_session(workspace: Path, session_id: str | None = None) -> dict[str, Any]:
    sid = session_id or current_session_id(workspace)
    jsonl = session_jsonl_path(workspace, sid)
    if jsonl.is_file():
        repo = _session_repo(workspace, sid)
        state = repo.materialize_session_state()
        messages = repo.materialize_messages()
        if messages:
            state["messages"] = messages
        return state
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
    snapshot = dict(payload)
    messages = [dict(item) for item in snapshot.pop("messages", []) if isinstance(item, dict)]
    existing = repo.materialize_messages()

    # Backfill old snapshot-only sessions once, then continue with message deltas.
    if not existing:
        legacy_messages = repo.materialize_session_state().get("messages") or []
        if isinstance(legacy_messages, list):
            for message in legacy_messages:
                if isinstance(message, dict):
                    repo.append("message", {"message": dict(message), "migrated": True})
            existing = repo.materialize_messages()

    if len(messages) >= len(existing) and messages[: len(existing)] == existing:
        for message in messages[len(existing) :]:
            repo.append(
                "message",
                {
                    "message": message,
                    "run_id": snapshot.get("task_id"),
                },
            )
    elif messages != existing:
        # Compression/rewrite replaces the active materialized transcript while
        # the old nodes remain available on the append-only tree.
        repo.append(
            "compression",
            {
                "messages": messages,
                "run_id": snapshot.get("task_id"),
            },
        )

    repo.append(
        "run",
        {
            "session_snapshot": snapshot,
            "run_id": snapshot.get("task_id"),
            "message_count": len(messages),
        },
    )


def ensure_session(workspace: Path, session_id: str | None = None) -> str:
    """Materialize the session file (root node) so it shows up in listings."""
    sid = session_id or current_session_id(workspace)
    _session_repo(workspace, sid)
    return sid
