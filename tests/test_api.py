from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coderking.api.app import create_app
from coderking.config import Settings
from coderking.controller import TaskController
from coderking.runtime.checkpoints import CheckpointStore
from coderking.runtime.state import AgentState, TaskStatus


def test_health() -> None:
    client = TestClient(create_app(TaskController()))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_diff_and_rollback_routes(tmp_path: Path) -> None:
    controller = TaskController()
    state = AgentState(task="x", repository=str(tmp_path))
    state.status = TaskStatus.SUCCEEDED
    (tmp_path / "a.py").write_text("old\n", encoding="utf-8")
    from coderking.diffing import snapshot_workspace

    state.snapshot = snapshot_workspace(tmp_path)
    (tmp_path / "a.py").write_text("new\n", encoding="utf-8")
    from coderking.controller import ManagedTask

    managed = ManagedTask(state=state, workspace=tmp_path)
    controller.tasks[state.task_id] = managed
    client = TestClient(create_app(controller))
    diff = client.get(f"/api/tasks/{state.task_id}/diff")
    assert diff.status_code == 200
    assert "new" in diff.json()["diff"]
    rolled = client.post(f"/api/tasks/{state.task_id}/rollback")
    assert rolled.status_code == 200
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "old\n"
    stop = client.post(f"/api/tasks/{state.task_id}/interrupt")
    assert stop.status_code == 200


def test_rollback_without_baseline_is_rejected(tmp_path: Path) -> None:
    controller = TaskController()
    state = AgentState(task="x", repository=str(tmp_path))
    state.status = TaskStatus.FAILED
    from coderking.controller import ManagedTask

    controller.tasks[state.task_id] = ManagedTask(state=state, workspace=tmp_path)
    (tmp_path / "keep.txt").write_text("safe", encoding="utf-8")
    client = TestClient(create_app(controller))

    response = client.post(f"/api/tasks/{state.task_id}/rollback")

    assert response.status_code == 409
    assert (tmp_path / "keep.txt").is_file()


def test_active_task_cannot_be_accepted_or_rolled_back(tmp_path: Path) -> None:
    from coderking.controller import ManagedTask
    from coderking.diffing import snapshot_workspace

    controller = TaskController(Settings(workspace=tmp_path, openai_api_key="x"))
    target = tmp_path / "a.txt"
    target.write_text("before", encoding="utf-8")
    state = AgentState(task="active", repository=str(tmp_path), task_id="active-task")
    state.snapshot = snapshot_workspace(tmp_path)
    state.status = TaskStatus.RUNNING
    controller.tasks[state.task_id] = ManagedTask(state=state, workspace=tmp_path)
    target.write_text("during run", encoding="utf-8")
    client = TestClient(create_app(controller))

    rolled = client.post(f"/api/tasks/{state.task_id}/rollback")
    accepted = client.post(f"/api/tasks/{state.task_id}/accept")

    assert rolled.status_code == 409
    assert accepted.status_code == 409
    assert target.read_text(encoding="utf-8") == "during run"


def test_retry_rejects_successful_task(tmp_path: Path) -> None:
    from coderking.controller import ManagedTask

    controller = TaskController(Settings(workspace=tmp_path, openai_api_key="x"))
    state = AgentState(task="done", repository=str(tmp_path))
    state.status = TaskStatus.SUCCEEDED
    controller.tasks[state.task_id] = ManagedTask(state=state, workspace=tmp_path)
    client = TestClient(create_app(controller))

    response = client.post(f"/api/tasks/{state.task_id}/retry")

    assert response.status_code == 409
    assert "only failed or interrupted" in response.json()["detail"]


def test_checkpoint_routes_list_and_restore(tmp_path: Path) -> None:
    from coderking.controller import ManagedTask

    controller = TaskController(Settings(workspace=tmp_path, openai_api_key="x"))
    state = AgentState(task="edit", repository=str(tmp_path), task_id="checkpoint-api")
    state.status = TaskStatus.SUCCEEDED
    controller.tasks[state.task_id] = ManagedTask(state=state, workspace=tmp_path)
    target = tmp_path / "a.txt"
    target.write_text("before", encoding="utf-8")
    store = CheckpointStore(tmp_path, tmp_path, state.task_id)
    prepared = store.prepare(
        turn_id="turn_a",
        tool_call_id="call_a",
        tool="edit",
        arguments={"path": "a.txt"},
    )
    assert prepared is not None
    target.write_text("after", encoding="utf-8")
    store.complete(prepared.checkpoint_id, ok=True)
    client = TestClient(create_app(controller))

    listed = client.get(f"/api/tasks/{state.task_id}/checkpoints")
    restored = client.post(
        f"/api/tasks/{state.task_id}/checkpoints/{prepared.checkpoint_id}/rollback"
    )

    assert listed.status_code == 200
    assert listed.json()["checkpoints"][0]["checkpoint_id"] == prepared.checkpoint_id
    assert restored.status_code == 200
    assert target.read_text(encoding="utf-8") == "before"


def test_api_token_required_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODERKING_API_TOKEN", "secret-token")
    controller = TaskController(Settings(workspace=tmp_path, openai_api_key="x"))
    client = TestClient(create_app(controller))
    denied = client.get("/api/workspace/tree")
    assert denied.status_code == 401
    ok = client.get("/api/workspace/tree", headers={"X-CoderKing-Token": "secret-token"})
    assert ok.status_code == 200
    assert ok.json()["root"] == str(tmp_path.resolve())


def test_repository_must_stay_inside_configured_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODERKING_API_TOKEN", raising=False)
    monkeypatch.delenv("CODERKING_HTTP_AUTO_APPROVE", raising=False)
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    controller = TaskController(Settings(workspace=allowed, openai_api_key="x"))
    client = TestClient(create_app(controller))
    response = client.post(
        "/api/tasks",
        json={"prompt": "hi", "repository": str(outside)},
    )
    assert response.status_code == 403


def test_http_auto_approve_requires_env_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODERKING_API_TOKEN", raising=False)
    monkeypatch.delenv("CODERKING_HTTP_AUTO_APPROVE", raising=False)
    controller = TaskController(Settings(workspace=tmp_path, openai_api_key="x"))
    client = TestClient(create_app(controller))
    response = client.post(
        "/api/tasks",
        json={"prompt": "hi", "auto_approve": True},
    )
    assert response.status_code == 403
    assert "CODERKING_HTTP_AUTO_APPROVE" in response.json()["detail"]
