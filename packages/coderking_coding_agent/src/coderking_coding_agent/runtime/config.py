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


@dataclass(frozen=True)
class RuntimeBindings:
    """Facade-only services injected so L2 never imports ``coderking``."""

    resolve_system_prompt: PromptResolver
    create_sandbox: Callable[[Path, CowWorkspace | None], Awaitable[tuple[Sandbox, str]]]
    build_tools: Callable[[Path, Sandbox], Mapping[str, Tool]]
    cancel_requested: Callable[[Path, str], bool]
    persist_state: Callable[[Path, AgentState], None]
    connect_mcp: Callable[[Path], Awaitable[Any]] | None = None


# Back-compat aliases while call sites migrate.
HarnessConfig = RuntimeConfig
HarnessBindings = RuntimeBindings
