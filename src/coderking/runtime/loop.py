"""Facade AgentRuntime — Pi-style pure coding-agent loop only."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from coderking.config import Settings
from coderking.mcp.host import McpHost
from coderking.prompts.loader import resolve_system_prompt
from coderking.registry import cancel_requested, persist_state
from coderking.runtime.cancel import CancellationToken
from coderking.sandbox.cow import CowWorkspace
from coderking.sandbox.manager import create_sandbox
from coderking.tools.registry import build_tools
from coderking_coding_agent.runtime.atomic_l1 import AtomicL1Runtime
from coderking_coding_agent.runtime.config import RuntimeBindings, RuntimeConfig
from coderking_coding_agent.runtime.events import AgentEvent
from coderking_coding_agent.runtime.queues import RunMessageQueues
from coderking_coding_agent.runtime.state import AgentState
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

    return RuntimeBindings(
        resolve_system_prompt=lambda: resolve_system_prompt(settings),
        create_sandbox=_create_sandbox,
        build_tools=lambda workspace, sandbox: build_tools(workspace, sandbox, settings),
        cancel_requested=cancel_requested,
        persist_state=persist_state,
        connect_mcp=_connect_mcp,
    )


def _config_for(settings: Settings) -> RuntimeConfig:
    return RuntimeConfig(
        max_iterations=settings.max_iterations,
        sandbox_cow=settings.sandbox_cow,
        sandbox_timeout_sec=settings.sandbox_timeout_sec,
        sandbox_rollback_on_interrupt=settings.sandbox_rollback_on_interrupt,
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
    ) -> AgentState:
        self._backend.system_prompt = resolve_system_prompt(
            self.settings, test_command=test_command
        )
        return await self._backend.run(
            prompt,
            workspace,
            on_event=on_event,
            queues=queues,
            state=state,
            approve=approve,
            auto_approve=auto_approve,
        )


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
