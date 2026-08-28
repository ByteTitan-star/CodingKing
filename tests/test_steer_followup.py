from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coderking.api.app import create_app
from coderking.controller import ManagedTask, TaskController
from coderking.runtime.events import AgentEvent
from coderking.runtime.loop import _inject_follow_up, _inject_steering_messages
from coderking.runtime.queues import RunMessageQueues
from coderking.runtime.state import AgentState, Role, TaskStatus


@pytest.mark.asyncio
async def test_inject_steering_messages() -> None:
    state = AgentState(task="t", repository=".")
    events: list[str] = []

    async def on_event(event: AgentEvent) -> None:
        events.append(event.type)

    await _inject_steering_messages(state, ["change plan"], on_event)
    assert state.messages[-1]["content"] == "[steer] change plan"
    assert events == ["steer"]


@pytest.mark.asyncio
async def test_inject_follow_up_keeps_run_alive() -> None:
    state = AgentState(task="t", repository=".", role=Role.REVIEWER)
    state.status = TaskStatus.RUNNING
    queues = RunMessageQueues()
    queues.enqueue_follow_up("commit when done")
    events: list[str] = []

    async def on_event(event: AgentEvent) -> None:
        events.append(event.type)

    applied = await _inject_follow_up(state, queues, on_event)
    assert applied is True
    assert state.status == TaskStatus.RUNNING
    assert "[follow-up]" in state.messages[-1]["content"]
    assert "follow_up" in events


def test_api_steer_and_follow_up_routes(tmp_path: Path) -> None:
    controller = TaskController()
    state = AgentState(task="x", repository=str(tmp_path))
    managed = ManagedTask(state=state, workspace=tmp_path)
    controller.tasks[state.task_id] = managed
    client = TestClient(create_app(controller))

    steer = client.post(
        f"/api/tasks/{state.task_id}/steer",
        json={"content": "focus on tests"},
    )
    assert steer.status_code == 200
    follow = client.post(
        f"/api/tasks/{state.task_id}/follow-up",
        json={"content": "commit when done"},
    )
    assert follow.status_code == 200
