"""Resolve optional runtime resources while preserving the atomic default surface."""

from __future__ import annotations

from pathlib import Path

from coderking.config import Settings
from coderking.mcp.host import McpHost
from coderking.sandbox.base import Sandbox
from coderking.tools.dynamic_adapter import wrap_dynamic_tools
from coderking.tools.dynamic_runner import SandboxToolRunner
from coderking.tools.registry import build_atomic_tools
from coderking_coding_agent.runtime.config import RuntimeResources
from coderking_coding_agent.tools.base import Tool
from coderking_coding_agent.tools.dynamic import DynamicToolLoader


def _merge_tools(
    target: dict[str, Tool],
    optional: dict[str, Tool],
    *,
    source: str,
    diagnostics: list[str],
) -> None:
    for name, tool in optional.items():
        if name in target:
            diagnostics.append(
                f"{source} tool {name!r} conflicts with an existing tool and was skipped"
            )
            continue
        target[name] = tool


class ResourceLoader:
    """Build the per-run tool surface from explicitly enabled resource families."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def load(self, workspace: Path, sandbox: Sandbox) -> RuntimeResources:
        root = workspace.resolve()
        tools = dict(build_atomic_tools(root, sandbox, self.settings))
        diagnostics: list[str] = []

        if self.settings.dynamic_tools_enabled:
            runner = SandboxToolRunner(sandbox, timeout_sec=self.settings.sandbox_timeout_sec)
            loader = DynamicToolLoader(
                root,
                runner,
                timeout_sec=self.settings.sandbox_timeout_sec,
            )
            try:
                dynamic_tools = wrap_dynamic_tools(loader.refresh())
            except Exception as exc:  # optional resources cannot remove atomic tools
                diagnostics.append(f"dynamic tool loading failed: {exc}")
            else:
                diagnostics.extend(
                    f"dynamic tool {name!r}: {message}"
                    for name, message in sorted(loader.errors.items())
                )
                _merge_tools(
                    tools,
                    dynamic_tools,
                    source="dynamic",
                    diagnostics=diagnostics,
                )

        host: McpHost | None = None
        if self.settings.mcp_enabled:
            try:
                host = await McpHost.connect(
                    root,
                    timeout_sec=self.settings.mcp_timeout_sec,
                )
            except Exception as exc:  # optional MCP failures are isolated
                diagnostics.append(f"MCP loading failed: {exc}")
                host = None
            else:
                _merge_tools(
                    tools,
                    host.tools(),
                    source="MCP",
                    diagnostics=diagnostics,
                )

        return RuntimeResources(
            tools=tools,
            diagnostics=tuple(diagnostics),
            close=host.close if host is not None else None,
        )
