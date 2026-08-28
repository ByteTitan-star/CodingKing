"""Wire TaskController to JSON-RPC stdio transport (#34)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from coderking.config import Settings, load_settings
from coderking.controller import TaskController
from coderking_coding_agent.session.repo import SessionRepo
from coderking_transport.rpc.stdio import StdioJsonRpcServer


class RpcService:
    def __init__(
        self,
        workspace: Path,
        *,
        settings: Settings | None = None,
        controller: TaskController | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings or load_settings(workspace=self.workspace)
        self.controller = controller or TaskController(self.settings)
        self._idle_events: dict[str, asyncio.Event] = {}
        self._event_tasks: dict[str, asyncio.Task[None]] = {}
        self.server = StdioJsonRpcServer(self._handlers())

    def _handlers(self) -> dict[str, Any]:
        return {
            "agent.prompt": self._agent_prompt,
            "agent.steer": self._agent_steer,
            "agent.follow_up": self._agent_follow_up,
            "agent.abort": self._agent_abort,
            "agent.wait_idle": self._agent_wait_idle,
            "agent.get_task": self._agent_get_task,
            "agent.diff": self._agent_diff,
            "agent.tree": self._agent_tree,
            "agent.read_file": self._agent_read_file,
            "agent.approve": self._agent_approve,
            "agent.reject": self._agent_reject,
            "agent.rollback": self._agent_rollback,
            "agent.accept": self._agent_accept,
            "session.load": self._session_load,
            "session.branch": self._session_branch,
        }

    async def run(self) -> None:
        await self.server.serve_forever()

    async def _agent_prompt(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        text = str(params.get("text") or "").strip()
        if not text:
            raise ValueError("params.text is required")
        auto_approve = bool(params.get("auto_approve", False))
        test_command = params.get("test_command")
        task = await self.controller.create_task(
            text,
            self.workspace,
            auto_approve=auto_approve,
            test_command=str(test_command) if test_command else None,
        )
        task_id = task.state.task_id
        idle = asyncio.Event()
        self._idle_events[task_id] = idle
        self._event_tasks[task_id] = asyncio.create_task(self._forward_events(task_id, idle))
        return {"task_id": task_id}

    async def _forward_events(self, task_id: str, idle: asyncio.Event) -> None:
        try:
            async for record in self.controller.subscribe_records(task_id):
                await self.server.notify("agent.event", record)
        finally:
            idle.set()
            self._idle_events.pop(task_id, None)
            self._event_tasks.pop(task_id, None)

    async def _agent_steer(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        content = str(params.get("content") or "")
        await self.controller.steer(task_id, content)
        return {"ok": True}

    async def _agent_follow_up(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        content = str(params.get("content") or "")
        await self.controller.follow_up(task_id, content)
        return {"ok": True}

    async def _agent_abort(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        self.controller.interrupt(task_id)
        return {"ok": True}

    async def _agent_wait_idle(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        idle = self._idle_events.get(task_id)
        if idle is not None:
            await idle.wait()
        return {"status": "idle", "task_id": task_id}

    async def _agent_get_task(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        return self.controller.public_task(task_id)

    async def _agent_diff(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        return {"diff": self.controller.diff(task_id)}

    async def _agent_tree(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        return {"files": self.controller.tree(task_id)}

    async def _agent_read_file(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        rel = str(params.get("path") or "")
        if not rel:
            raise ValueError("params.path is required")
        return {"path": rel, "content": self.controller.read_file(task_id, rel)}

    async def _agent_approve(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        self.controller.resolve_approval(task_id, True)
        return {"ok": True}

    async def _agent_reject(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        self.controller.resolve_approval(task_id, False)
        return {"ok": True}

    async def _agent_rollback(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        self.controller.rollback(task_id)
        return {"ok": True}

    async def _agent_accept(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        _task_id = str(params.get("task_id") or "")
        return {"ok": True}

    async def _session_load(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("session_id") or "default")
        repo = SessionRepo(self.workspace, session_id=session_id)
        return {
            "session_id": session_id,
            "head_id": repo.head_id,
            "messages": repo.materialize_messages(),
            "state": repo.materialize_session_state(),
        }

    async def _session_branch(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("session_id") or "default")
        node_id = str(params.get("node_id") or "")
        if not node_id:
            raise ValueError("params.node_id is required")
        repo = SessionRepo(self.workspace, session_id=session_id)
        repo.branch_to(node_id)
        return {"head_id": repo.head_id, "session_id": session_id}


async def run_rpc_server(workspace: Path, *, settings: Settings | None = None) -> None:
    service = RpcService(workspace, settings=settings)
    await service.run()
