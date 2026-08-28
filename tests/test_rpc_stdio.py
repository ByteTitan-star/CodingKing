from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from coderking.controller import TaskController
from coderking.rpc import RpcService
from coderking.runtime.state import AgentState
from coderking_transport.rpc.jsonrpc import (
    JsonRpcError,
    format_notification,
    format_response,
    parse_request,
)
from coderking_transport.rpc.stdio import StdioJsonRpcServer


def test_parse_request_valid() -> None:
    payload = parse_request(
        '{"jsonrpc":"2.0","id":1,"method":"agent.prompt","params":{"text":"hi"}}'
    )
    assert payload["method"] == "agent.prompt"


def test_parse_request_invalid_version() -> None:
    with pytest.raises(JsonRpcError):
        parse_request('{"jsonrpc":"1.0","id":1,"method":"x","params":{}}')


def test_format_response_and_notification() -> None:
    response = json.loads(format_response(7, {"ok": True}))
    notification = json.loads(format_notification("agent.event", {"type": "done"}))
    assert response["id"] == 7
    assert notification["method"] == "agent.event"
    assert "id" not in notification


@pytest.mark.asyncio
async def test_stdio_server_dispatches_handler() -> None:
    stdout = io.StringIO()
    server = StdioJsonRpcServer(
        {"echo.ping": _echo_ping},
        stdin=io.StringIO(),
        stdout=stdout,
    )
    await server.handle_request('{"jsonrpc":"2.0","id":1,"method":"echo.ping","params":{"x":1}}')
    out = stdout.getvalue().strip()
    payload = json.loads(out)
    assert payload["result"] == {"x": 1}


async def _echo_ping(_method: str, params: dict[str, Any]) -> dict[str, Any]:
    return params


@pytest.mark.asyncio
async def test_rpc_service_prompt_and_events(tmp_path: Path) -> None:
    stdout = io.StringIO()
    controller = MagicMock(spec=TaskController)
    state = AgentState(task="demo", repository=str(tmp_path))
    managed = MagicMock()
    managed.state = state

    async def create_task(*args: Any, **kwargs: Any):  # noqa: ANN401, ARG001
        return managed

    async def subscribe_records(task_id: str):  # noqa: ANN001
        yield {"id": f"{task_id}-000001", "type": "done", "payload": {"ok": True}}

    controller.create_task = AsyncMock(side_effect=create_task)
    controller.subscribe_records = subscribe_records

    service = RpcService(tmp_path, controller=controller)
    service.server.stdout = stdout

    result = await service._agent_prompt("agent.prompt", {"text": "fix bug"})
    assert result["task_id"] == state.task_id
    await asyncio.wait_for(service._event_tasks[state.task_id], timeout=5)

    lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["method"] == "agent.event"
    assert event["params"]["type"] == "done"


@pytest.mark.asyncio
async def test_rpc_service_session_branch(tmp_path: Path) -> None:
    from coderking_coding_agent.session.repo import SessionRepo

    repo = SessionRepo(tmp_path, session_id="rpc-test")
    node = repo.append("message", {"message": {"role": "user", "content": "hello"}})
    service = RpcService(tmp_path, controller=MagicMock(spec=TaskController))
    loaded = await service._session_load("session.load", {"session_id": "rpc-test"})
    assert loaded["head_id"] == node.id
    branched = await service._session_branch(
        "session.branch",
        {"session_id": "rpc-test", "node_id": node.id},
    )
    assert branched["head_id"] == node.id


@pytest.mark.asyncio
async def test_notification_throughput_without_deadlock() -> None:
    stdout = io.StringIO()
    server = StdioJsonRpcServer({}, stdout=stdout)

    async def emit_many() -> None:
        for index in range(1000):
            await server.notify("agent.event", {"index": index})

    await asyncio.wait_for(emit_many(), timeout=10)
    assert stdout.getvalue().count('"method":"agent.event"') == 1000


@pytest.mark.asyncio
async def test_rpc_service_task_query_and_control(tmp_path: Path) -> None:
    controller = MagicMock(spec=TaskController)
    state = AgentState(task="demo", repository=str(tmp_path))
    controller.public_task.return_value = {"task_id": state.task_id, "status": "running"}
    controller.diff.return_value = "diff-text"
    controller.tree.return_value = ["a.py"]
    controller.read_file.return_value = "print('x')"
    service = RpcService(tmp_path, controller=controller)

    task = await service._agent_get_task("agent.get_task", {"task_id": state.task_id})
    assert task["task_id"] == state.task_id
    diff = await service._agent_diff("agent.diff", {"task_id": state.task_id})
    assert diff["diff"] == "diff-text"
    tree = await service._agent_tree("agent.tree", {"task_id": state.task_id})
    assert tree["files"] == ["a.py"]
    content = await service._agent_read_file(
        "agent.read_file", {"task_id": state.task_id, "path": "a.py"}
    )
    assert content["content"] == "print('x')"
    await service._agent_approve("agent.approve", {"task_id": state.task_id})
    controller.resolve_approval.assert_called_once_with(state.task_id, True)
    await service._agent_rollback("agent.rollback", {"task_id": state.task_id})
    controller.rollback.assert_called_once_with(state.task_id)
