from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from coderking.config import Settings, load_settings
from coderking.diffing import restore_snapshot, unified_diff
from coderking.llm.openai_compat import OpenAICompatProvider
from coderking.memory.store import MemoryStore
from coderking.registry import request_cancel
from coderking.runtime.cancel import CancellationToken
from coderking.runtime.events import AgentEvent
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.queues import RunMessageQueues
from coderking.runtime.state import AgentState, TaskStatus
from coderking.workspace import ensure_inside, iter_files


@dataclass
class ManagedTask:
    state: AgentState
    workspace: Path
    events: asyncio.Queue[dict[str, Any] | None] = field(default_factory=asyncio.Queue)
    approval: asyncio.Future[bool] | None = None
    cancel: CancellationToken = field(default_factory=CancellationToken)
    snapshot: list[dict[str, Any]] = field(default_factory=list)
    queues: RunMessageQueues = field(default_factory=RunMessageQueues)
    event_seq: int = 0


class TaskController:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self.tasks: dict[str, ManagedTask] = {}
        self._lock = asyncio.Lock()

    def _runtime(self, cancel: CancellationToken) -> AgentRuntime:
        memory_path = self.settings.resolved_workspace() / ".coderking" / "memory.db"
        return AgentRuntime(
            self.settings,
            OpenAICompatProvider(self.settings),
            memory=MemoryStore(memory_path),
            cancel=cancel,
        )

    def _record_event(self, task: ManagedTask, event: AgentEvent) -> dict[str, Any]:
        task.event_seq += 1
        record = {"id": f"{task.state.task_id}-{task.event_seq:06d}", **event.as_dict()}
        task.snapshot.append(record)
        return record

    async def create_task(
        self,
        prompt: str,
        workspace: Path | None = None,
        *,
        auto_approve: bool = False,
        test_command: str | None = None,
        state: AgentState | None = None,
    ) -> ManagedTask:
        root = (workspace or self.settings.resolved_workspace()).resolve()
        managed = ManagedTask(
            state=state or AgentState(task=prompt, repository=str(root)),
            workspace=root,
        )
        async with self._lock:
            self.tasks[managed.state.task_id] = managed

        async def on_event(event: AgentEvent) -> None:
            record = self._record_event(managed, event)
            await managed.events.put(record)

        async def approve(_tool: str, _reason: str, _args: dict[str, Any]) -> bool:
            loop = asyncio.get_running_loop()
            managed.approval = loop.create_future()
            return await managed.approval

        async def runner() -> None:
            try:
                await self._runtime(managed.cancel).run(
                    prompt,
                    root,
                    on_event=on_event,
                    approve=None if auto_approve else approve,
                    auto_approve=auto_approve,
                    test_command=test_command,
                    state=managed.state,
                    queues=managed.queues,
                )
            finally:
                await managed.events.put(None)

        asyncio.create_task(runner())
        return managed

    def get(self, task_id: str) -> ManagedTask:
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def resolve_approval(self, task_id: str, allowed: bool) -> None:
        task = self.get(task_id)
        if task.approval and not task.approval.done():
            task.approval.set_result(allowed)

    def interrupt(self, task_id: str) -> None:
        task = self.get(task_id)
        task.state.status = TaskStatus.INTERRUPTED
        task.state.cancel_requested = True
        task.cancel.cancel()
        request_cancel(task.workspace, task_id)

    async def steer(self, task_id: str, content: str) -> None:
        task = self.get(task_id)
        task.queues.enqueue_steer(content)
        from coderking.runtime.events import steer_event

        record = self._record_event(task, steer_event(content))
        await task.events.put(record)

    async def follow_up(self, task_id: str, content: str) -> None:
        task = self.get(task_id)
        task.queues.enqueue_follow_up(content)
        from coderking.runtime.events import follow_up_event

        record = self._record_event(task, follow_up_event(content))
        await task.events.put(record)

    def rollback(self, task_id: str) -> None:
        task = self.get(task_id)
        restore_snapshot(task.workspace, task.state.snapshot)
        task.state.changed_files = []

    def diff(self, task_id: str) -> str:
        task = self.get(task_id)
        return unified_diff(task.workspace, task.state.snapshot)

    async def subscribe_records(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        task = self.get(task_id)
        while True:
            record = await task.events.get()
            if record is None:
                break
            yield record

    async def subscribe(self, task_id: str) -> AsyncIterator[AgentEvent]:
        async for record in self.subscribe_records(task_id):
            yield AgentEvent(record["type"], record.get("payload", {}))

    def tree(self, task_id: str) -> list[str]:
        task = self.get(task_id)
        root = task.workspace
        return [p.relative_to(root).as_posix() for p in iter_files(root, max_files=500)]

    def read_file(self, task_id: str, rel: str) -> str:
        task = self.get(task_id)
        path = ensure_inside(task.workspace, Path(rel))
        return path.read_text(encoding="utf-8", errors="replace")

    def public_task(self, task_id: str) -> dict[str, Any]:
        task = self.get(task_id)
        state = task.state
        return {
            "task_id": state.task_id,
            "prompt": state.task,
            "status": state.status.value,
            "role": state.role.value,
            "iteration": state.iteration,
            "plan": [asdict(item) for item in state.plan],
            "changed_files": state.changed_files,
            "test_results": state.test_results,
            "model": self.settings.model,
            "sandbox": {
                "backend": state.sandbox_backend,
                "status": state.sandbox_status,
            },
            "tokens": {"prompt": state.token_input, "completion": state.token_output},
            "errors": state.errors,
            "events": task.snapshot[-200:],
        }


CONTROLLER = TaskController()
