"""MCP host: manage stdio servers and expose namespaced tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from coderking.mcp.client import McpStdioSession, McpToolInfo
from coderking.mcp.config import McpConfig, load_mcp_config
from coderking.tools.base import Tool, ToolResult


class McpTool(Tool):
    """Bridge an MCP server tool into the Phase-1 Tool registry."""

    requires_approval = True  # default ask (#43)

    def __init__(self, info: McpToolInfo, session: McpStdioSession) -> None:
        self._info = info
        self._session = session
        self.name = info.namespaced
        self.description = f"[MCP:{info.server}] {info.description}"
        schema = dict(info.input_schema) if info.input_schema else {}
        if schema.get("type") != "object":
            schema = {"type": "object", "properties": schema.get("properties") or {}}
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        self.parameters = schema

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            ok, output = await self._session.call_tool(self._info.name, dict(kwargs))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, f"MCP call failed: {exc}")
        return ToolResult(ok, output)


class McpHost:
    def __init__(self) -> None:
        self._sessions: list[McpStdioSession] = []
        self._tools: dict[str, McpTool] = {}

    @classmethod
    async def connect(
        cls,
        workspace: Path,
        *,
        config: McpConfig | None = None,
        timeout_sec: float = 60.0,
    ) -> McpHost:
        host = cls()
        cfg = config if config is not None else load_mcp_config(workspace)
        for server in cfg.selected():
            session = McpStdioSession(server, timeout_sec=timeout_sec)
            await session.start()
            host._sessions.append(session)
            for info in session.tools:
                tool = McpTool(info, session)
                host._tools[tool.name] = tool
        return host

    def tools(self) -> dict[str, Tool]:
        return dict(self._tools)

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    async def close(self) -> None:
        for session in self._sessions:
            await session.close()
        self._sessions.clear()
        self._tools.clear()
