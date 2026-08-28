from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from coderking.api.app import create_app
from coderking.controller import ManagedTask, TaskController
from coderking.runtime.state import AgentState
from coderking_transport.http.sse import events_since, format_sse_event, stream_task_events


def test_format_sse_event_includes_id_type_and_data() -> None:
    frame = format_sse_event(
        {
            "id": "task-000001",
            "type": "tool_call",
            "payload": {"tool": "read", "status": "running"},
        }
    )
    assert "id: task-000001" in frame
    assert "event: tool_call" in frame
    assert 'data: {"tool":"read","status":"running"}' in frame
    assert frame.endswith("\n\n")


def test_events_since_replays_after_last_event_id() -> None:
    records = [
        {"id": "a", "type": "one", "payload": {}},
        {"id": "b", "type": "two", "payload": {}},
        {"id": "c", "type": "three", "payload": {}},
    ]
    replay = events_since(records, "b")
    assert [item["id"] for item in replay] == ["c"]


def test_events_since_returns_all_when_no_last_id() -> None:
    records = [{"id": "a", "type": "one", "payload": {}}]
    assert events_since(records, None) == records


class _StubController:
    def __init__(self, task: ManagedTask) -> None:
        self.task = task

    def get(self, task_id: str) -> ManagedTask:
        if task_id != self.task.state.task_id:
            raise KeyError(task_id)
        return self.task

    async def subscribe_records(self, task_id: str):  # noqa: ANN204
        yield {"id": f"{task_id}-000003", "type": "done", "payload": {"ok": True}}


@pytest.mark.asyncio
async def test_stream_task_events_replays_then_live() -> None:
    state = AgentState(task="demo", repository=".")
    task = ManagedTask(state=state, workspace=Path("."))
    task.snapshot = [
        {"id": f"{state.task_id}-000001", "type": "agent_status", "payload": {"status": "running"}},
        {"id": f"{state.task_id}-000002", "type": "token_usage", "payload": {"prompt": 1}},
    ]
    controller = _StubController(task)
    frames = [
        frame
        async for frame in stream_task_events(
            controller,
            state.task_id,
            last_event_id=f"{state.task_id}-000001",
        )
    ]
    assert len(frames) == 2
    assert f"id: {state.task_id}-000002" in frames[0]
    assert f"id: {state.task_id}-000003" in frames[1]


@pytest.mark.asyncio
async def test_sse_endpoint_replay_with_last_event_id(tmp_path: Path) -> None:
    controller = TaskController()
    state = AgentState(task="demo", repository=str(tmp_path))
    managed = ManagedTask(state=state, workspace=tmp_path, event_seq=2)
    managed.snapshot = [
        {
            "id": f"{state.task_id}-000001",
            "type": "agent_status",
            "payload": {"role": "planner", "status": "running"},
        },
        {
            "id": f"{state.task_id}-000002",
            "type": "done",
            "payload": {"ok": True, "summary": "finished"},
        },
    ]
    controller.tasks[state.task_id] = managed
    await managed.events.put(None)

    transport = ASGITransport(app=create_app(controller))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "GET",
            f"/api/v2/tasks/{state.task_id}/events",
            headers={
                "Accept": "text/event-stream",
                "Last-Event-ID": f"{state.task_id}-000001",
            },
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = (await response.aread()).decode("utf-8")
    assert f"id: {state.task_id}-000002" in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_many_concurrent_sse_replays(tmp_path: Path) -> None:
    controller = TaskController()
    tasks: list[ManagedTask] = []
    for index in range(20):
        state = AgentState(task=f"task-{index}", repository=str(tmp_path))
        managed = ManagedTask(state=state, workspace=tmp_path, event_seq=1)
        managed.snapshot = [
            {
                "id": f"{state.task_id}-000001",
                "type": "done",
                "payload": {"ok": True, "summary": str(index)},
            }
        ]
        controller.tasks[state.task_id] = managed
        tasks.append(managed)

    transport = ASGITransport(app=create_app(controller))

    async def read_one(task: ManagedTask) -> str:
        await task.events.put(None)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                f"/api/v2/tasks/{task.state.task_id}/events",
                headers={"Accept": "text/event-stream"},
            )
            return response.text

    bodies = await asyncio.gather(*(read_one(task) for task in tasks))
    assert len(bodies) == 20
    assert all("event: done" in body for body in bodies)
