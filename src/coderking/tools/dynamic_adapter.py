"""Dynamic tool adapters for Phase 1 Tool registry."""

from __future__ import annotations

from typing import Any

from coderking.tools.base import Tool, ToolResult
from coderking_coding_agent.tools.dynamic import DynamicToolExecutor


class DynamicTool(Tool):
    requires_approval = True

    def __init__(self, executor: DynamicToolExecutor) -> None:
        self._executor = executor
        self.name = executor.name
        self.description = executor.description
        self.parameters = executor.parameters

    async def execute(self, **kwargs: Any) -> ToolResult:
        ok, output = await self._executor.execute(**kwargs)
        return ToolResult(ok, output)


def wrap_dynamic_tools(executors: dict[str, DynamicToolExecutor]) -> dict[str, Tool]:
    return {name: DynamicTool(ex) for name, ex in executors.items()}
