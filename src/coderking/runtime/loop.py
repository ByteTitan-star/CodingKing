"""Facade AgentRuntime — Pi-style pure coding-agent loop only."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from coderking.config import Settings
from coderking.mcp.host import McpHost
from coderking.prompts.loader import resolve_system_prompt
from coderking.registry import cancel_requested, clear_cancel, persist_state
from coderking.resources import ResourceLoader
from coderking.runtime.cancel import CancellationToken
from coderking.sandbox.cow import CowWorkspace
from coderking.sandbox.manager import create_sandbox
from coderking.tools.registry import build_tools
from coderking_coding_agent.runtime.atomic_l1 import AtomicL1Runtime
from coderking_coding_agent.runtime.config import RuntimeBindings, RuntimeConfig
from coderking_coding_agent.runtime.events import AgentEvent, done_event, error_event
from coderking_coding_agent.runtime.queues import RunMessageQueues
from coderking_coding_agent.runtime.state import AgentState, TaskStatus
from coderking_coding_agent.runtime.support import (
    _inject_follow_up,
    _inject_steering,
    _inject_steering_messages,
)
from coderking_llm.provider import LLMProvider

EventSink = Callable[[AgentEvent], Awaitable[None]]
ApprovalFn = Callable[[str, str, dict[str, Any]], Awaitable[bool]]


def _bindings_for(settings: Settings) -> RuntimeBindings:
    async def _create_sandbox(workspace: Path, cow: CowWorkspace | None):
        return await create_sandbox(workspace, settings, cow=cow)

    async def _connect_mcp(workspace: Path) -> Any:
        return await McpHost.connect(workspace)

    resource_loader = ResourceLoader(settings)

    return RuntimeBindings(
        resolve_system_prompt=lambda: resolve_system_prompt(settings),
        create_sandbox=_create_sandbox,
        build_tools=lambda workspace, sandbox: build_tools(workspace, sandbox, settings),
        cancel_requested=cancel_requested,
        clear_cancel=clear_cancel,
        persist_state=persist_state,
        load_resources=resource_loader.load,
        connect_mcp=_connect_mcp,
    )


def _config_for(settings: Settings) -> RuntimeConfig:
    return RuntimeConfig(
        max_iterations=settings.max_iterations,
        sandbox_cow=settings.sandbox_cow,
        sandbox_timeout_sec=settings.sandbox_timeout_sec,
        sandbox_rollback_on_interrupt=settings.sandbox_rollback_on_interrupt,
        context_window=settings.context_window,
        compression_enabled=settings.compression_enabled,
        compression_threshold=settings.compression_threshold,
        compression_reserve_tokens=settings.compression_reserve_tokens,
        compression_keep_recent_messages=settings.compression_keep_recent_messages,
    )


class AgentRuntime:
    """Single coding-agent runtime: L1 loop + read/write/edit/bash."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        *,
        memory: Any | None = None,
        cancel: CancellationToken | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.memory = memory
        self.cancel = cancel or CancellationToken()
        self._backend = AtomicL1Runtime(
            _config_for(settings),
            llm,
            _bindings_for(settings),
            system_prompt=resolve_system_prompt(settings),
            cancel=self.cancel,
        )

    async def run(
        self,
        prompt: str,
        workspace: Path,
        *,
        on_event: EventSink,
        approve: ApprovalFn | None = None,
        auto_approve: bool = False,
        test_command: str | None = None,
        state: AgentState | None = None,
        queues: RunMessageQueues | None = None,
        skill_names: Sequence[str] = (),
    ) -> AgentState:
        self._backend.system_prompt = resolve_system_prompt(
            self.settings, test_command=test_command
        )
        active_state = state or AgentState(task=prompt, repository=str(workspace.resolve()))
        clear_cancel(workspace, active_state.task_id)

        async def watch_external_cancel() -> None:
            while not self.cancel.cancelled:
                if cancel_requested(workspace, active_state.task_id):
                    active_state.cancel_requested = True
                    self.cancel.cancel()
                    return
                await asyncio.sleep(0.2)

        watcher = asyncio.create_task(watch_external_cancel())
        try:
            try:
                return await self._backend.run(
                    prompt,
                    workspace,
                    on_event=on_event,
                    queues=queues,
                    state=active_state,
                    approve=approve,
                    auto_approve=auto_approve,
                    skill_names=skill_names,
                )
            except Exception as exc:
                interrupted = self.cancel.cancelled
                active_state.status = TaskStatus.INTERRUPTED if interrupted else TaskStatus.FAILED
                active_state.errors.append(str(exc))
                persist_state(workspace, active_state)
                await on_event(error_event(str(exc)))
                await on_event(done_event(False, "interrupted" if interrupted else str(exc)))
                clear_cancel(workspace, active_state.task_id)
                return active_state
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher


# Back-compat aliases for renamed config types.
HarnessBindings = RuntimeBindings
HarnessConfig = RuntimeConfig

__all__ = [
    "AgentRuntime",
    "HarnessBindings",
    "HarnessConfig",
    "RuntimeBindings",
    "RuntimeConfig",
    "_inject_follow_up",
    "_inject_steering",
    "_inject_steering_messages",
]
