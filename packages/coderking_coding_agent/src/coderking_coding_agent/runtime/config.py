"""Runtime config and facade-injected bindings for the coding agent."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from coderking_coding_agent.runtime.state import AgentState
from coderking_coding_agent.sandbox.base import Sandbox
from coderking_coding_agent.sandbox.cow import CowWorkspace
from coderking_coding_agent.tools.base import Tool


class PromptResolver(Protocol):
    def __call__(self) -> str: ...


@dataclass(frozen=True)
class RuntimeConfig:
    max_iterations: int = 24
    sandbox_cow: bool = False
    sandbox_timeout_sec: int = 120
    sandbox_rollback_on_interrupt: bool = False
    context_window: int = 128_000
    compression_enabled: bool = True
    compression_threshold: float = 0.75
    compression_reserve_tokens: int = 4096
    compression_keep_recent_messages: int = 20
    micro_compaction_enabled: bool = True
    micro_compaction_threshold: float = 0.5
    micro_compaction_keep_recent_tool_results: int = 4
    micro_compaction_min_output_chars: int = 2_000
    # Claude-Code-style orchestration: adds plan + agent tools, the
    # orchestration prompt section and parallel per-turn tool execution.
    dynamic_workflow: bool = False
    subagent_max_turns: int = 16


@dataclass
class RuntimeResources:
    """One run's fully resolved tool surface and cleanup hook."""

    tools: Mapping[str, Tool]
    diagnostics: tuple[str, ...] = ()
    close: Callable[[], Awaitable[None]] | None = None

    async def aclose(self) -> None:
        if self.close is not None:
            await self.close()


@dataclass(frozen=True)
class RuntimeBindings:
    """Facade-only services injected so L2 never imports ``coderking``."""

    resolve_system_prompt: PromptResolver
    create_sandbox: Callable[[Path, CowWorkspace | None], Awaitable[tuple[Sandbox, str]]]
    build_tools: Callable[[Path, Sandbox], Mapping[str, Tool]]
    cancel_requested: Callable[[Path, str], bool]
    clear_cancel: Callable[[Path, str], None]
    persist_state: Callable[[Path, AgentState], None]
    load_resources: Callable[[Path, Sandbox], Awaitable[RuntimeResources]] | None = None
    connect_mcp: Callable[[Path], Awaitable[Any]] | None = None


# Back-compat aliases while call sites migrate.
HarnessConfig = RuntimeConfig
HarnessBindings = RuntimeBindings
