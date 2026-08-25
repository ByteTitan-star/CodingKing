from pathlib import Path

from fastapi.testclient import TestClient

from coderking.api.app import create_app
from coderking.controller import TaskController
from coderking.runtime.state import AgentState


def test_health() -> None:
    client = TestClient(create_app(TaskController()))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_diff_and_rollback_routes(tmp_path: Path) -> None:
    controller = TaskController()
    state = AgentState(task="x", repository=str(tmp_path))
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
