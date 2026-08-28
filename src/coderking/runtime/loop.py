"""Facade AgentRuntime — wires Settings into L2 SWE harness (#23)."""

from __future__ import annotations

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
from coderking_coding_agent.runtime.config import HarnessBindings, HarnessConfig
from coderking_coding_agent.runtime.loop import (
    AgentRuntime as L2AgentRuntime,
)
from coderking_coding_agent.runtime.loop import (
    _inject_follow_up,
    _inject_steering,
    _inject_steering_messages,
)
from coderking_coding_agent.runtime.state import Role
from coderking_llm.provider import LLMProvider


def _bindings_for(settings: Settings) -> HarnessBindings:
    async def _create_sandbox(workspace: Path, cow: CowWorkspace | None):
        return await create_sandbox(workspace, settings, cow=cow)

    async def _connect_mcp(workspace: Path) -> Any:
        return await McpHost.connect(workspace)

    return HarnessBindings(
        resolve_system_prompt=lambda role: resolve_system_prompt(settings, role),
        create_sandbox=_create_sandbox,
        build_tools=lambda workspace, sandbox: build_tools(workspace, sandbox, settings),
        cancel_requested=cancel_requested,
        persist_state=persist_state,
        connect_mcp=_connect_mcp,
    )


def _config_for(settings: Settings) -> HarnessConfig:
    return HarnessConfig(
        max_iterations=settings.max_iterations,
        sandbox_cow=settings.sandbox_cow,
        sandbox_timeout_sec=settings.sandbox_timeout_sec,
        sandbox_rollback_on_interrupt=settings.sandbox_rollback_on_interrupt,
    )


class AgentRuntime(L2AgentRuntime):
    """Compatibility wrapper preserving ``AgentRuntime(settings, llm, ...)``."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        *,
        memory: Any | None = None,
        cancel: CancellationToken | None = None,
    ) -> None:
        self.settings = settings
        super().__init__(
            _config_for(settings),
            llm,
            _bindings_for(settings),
            memory=memory,
            cancel=cancel,
        )


__all__ = [
    "AgentRuntime",
    "HarnessBindings",
    "HarnessConfig",
    "Role",
    "_inject_follow_up",
    "_inject_steering",
    "_inject_steering_messages",
]
