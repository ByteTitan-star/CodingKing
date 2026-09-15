"""Wire TaskController to JSON-RPC stdio transport (#34)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from coderking.config import Settings, load_settings
from coderking.controller import TaskController
from coderking.registry import list_sessions
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
            "agent.retry": self._agent_retry,
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
            "agent.checkpoints": self._agent_checkpoints,
            "agent.rollback_checkpoint": self._agent_rollback_checkpoint,
            "session.load": self._session_load,
            "session.branch": self._session_branch,
            "session.list": self._session_list,
            "config.get": self._config_get,
            "config.set": self._config_set,
        }

    async def run(self) -> None:
        await self.server.serve_forever()

    async def _agent_prompt(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        text = str(params.get("text") or "").strip()
        if not text:
            raise ValueError("params.text is required")
        auto_approve = bool(params.get("auto_approve", False))
        test_command = params.get("test_command")
        skills_raw = params.get("skills") or []
        valid_skills = isinstance(skills_raw, list) and all(
            isinstance(item, str) for item in skills_raw
        )
        if not valid_skills:
            raise ValueError("params.skills must be a list of skill names")
        task = await self.controller.create_task(
            text,
            self.workspace,
            auto_approve=auto_approve,
            test_command=str(test_command) if test_command else None,
            skill_names=skills_raw,
            session_id=str(params.get("session_id") or "") or None,
        )
        task_id = task.state.task_id
        idle = asyncio.Event()
        self._idle_events[task_id] = idle
        self._event_tasks[task_id] = asyncio.create_task(self._forward_events(task_id, idle))
        return {"task_id": task_id}

    async def _agent_retry(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        if not task_id:
            raise ValueError("params.task_id is required")
        skills_raw = params.get("skills") or []
        if not isinstance(skills_raw, list) or not all(
            isinstance(item, str) for item in skills_raw
        ):
            raise ValueError("params.skills must be a list of skill names")
        task = await self.controller.retry(
            task_id,
            prompt=str(params.get("text") or "") or None,
            auto_approve=bool(params.get("auto_approve", False)),
            test_command=str(params.get("test_command") or "") or None,
            skill_names=skills_raw,
        )
        new_task_id = task.state.task_id
        idle = asyncio.Event()
        self._idle_events[new_task_id] = idle
        self._event_tasks[new_task_id] = asyncio.create_task(
            self._forward_events(new_task_id, idle)
        )
        return {"task_id": new_task_id, "parent_run_id": task_id}

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
        await asyncio.to_thread(self.controller.rollback, task_id)
        return {"ok": True}

    async def _agent_accept(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        accepted = await asyncio.to_thread(self.controller.accept, task_id)
        return {"ok": True, "accepted_checkpoints": accepted}

    async def _agent_checkpoints(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        checkpoints = await asyncio.to_thread(self.controller.checkpoints, task_id)
        return {"checkpoints": checkpoints}

    async def _agent_rollback_checkpoint(
        self, _method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        task_id = str(params.get("task_id") or "")
        checkpoint_id = str(params.get("checkpoint_id") or "")
        if not checkpoint_id:
            raise ValueError("params.checkpoint_id is required")
        checkpoint = await asyncio.to_thread(
            self.controller.rollback_checkpoint,
            task_id,
            checkpoint_id,
        )
        return {"ok": True, "checkpoint": checkpoint}

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

    async def _session_list(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        limit = int(params.get("limit") or 50)
        metas = list_sessions(self.workspace)[:limit]
        running_sessions = {
            task.state.session_id
            for task in self.controller.tasks.values()
            if task.state.session_id
            and task.state.status.value in {"pending", "running", "waiting_approval"}
        }
        return {
            "sessions": [
                {
                    "session_id": meta.session_id,
                    "updated_at": meta.updated_at,
                    "prompt": meta.prompt,
                    "nodes": meta.nodes,
                    "tokens": {"prompt": meta.token_input, "completion": meta.token_output},
                    "running": meta.session_id in running_sessions,
                }
                for meta in metas
            ]
        }

    async def _config_get(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        effort = getattr(self.controller.settings, "reasoning_effort", None)
        return {
            "model": self.controller.settings.model,
            "workspace": str(self.workspace),
            "reasoning_effort": effort if effort is not None else "off",
        }

    async def _config_set(self, _method: str, params: dict[str, Any]) -> dict[str, Any]:
        model = str(params.get("model") or "").strip()
        effort = str(params.get("reasoning_effort") or "").strip()
        if not model and not effort:
            raise ValueError("params.model or params.reasoning_effort is required")
        if effort and effort not in {"off", "low", "medium", "high", "ultra"}:
            raise ValueError("params.reasoning_effort must be one of off/low/medium/high/ultra")
        if model:
            self.controller.settings.model = model
        if effort:
            self.controller.settings.reasoning_effort = effort
        return {
            "ok": True,
            "model": self.controller.settings.model,
            "reasoning_effort": self.controller.settings.reasoning_effort,
        }


async def run_rpc_server(workspace: Path, *, settings: Settings | None = None) -> None:
    service = RpcService(workspace, settings=settings)
    await service.run()
