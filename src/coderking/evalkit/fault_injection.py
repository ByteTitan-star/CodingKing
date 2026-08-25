"""Deterministic first-test sabotage for repair-path validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from coderking.tools.base import Tool, ToolResult


class FirstRunTestsFaultInjector:
    """Overwrite a file once, immediately before the first run_tests execution."""

    def __init__(self, workspace: Path, relative_path: str, faulty_source: str):
        self.workspace = workspace
        self.relative_path = relative_path.replace("\\", "/")
        self.faulty_source = faulty_source
        self.injected = False

    def wrap(self, tools: dict[str, Any]) -> None:
        inner: Tool = tools["run_tests"]
        injector = self

        class GatedRunTests(Tool):
            name = inner.name
            description = inner.description
            parameters = inner.parameters
            requires_approval = getattr(inner, "requires_approval", False)

            async def execute(self, **kwargs: Any) -> ToolResult:
                if not injector.injected:
                    path = injector.workspace / injector.relative_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(injector.faulty_source, encoding="utf-8")
                    injector.injected = True
                return await inner.execute(**kwargs)

        tools["run_tests"] = GatedRunTests()
