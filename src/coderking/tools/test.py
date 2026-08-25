from __future__ import annotations

from typing import Any

from coderking.sandbox.base import Sandbox
from coderking.tools.base import Tool, ToolResult


class RunTestsTool(Tool):
    name = "run_tests"
    description = "Run the project test command in the sandbox (default: python -m pytest -q)."
    parameters = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": [],
    }

    def __init__(
        self, sandbox: Sandbox, timeout_sec: int, default_command: str = "python -m pytest -q"
    ):
        self.sandbox = sandbox
        self.timeout_sec = timeout_sec
        self.default_command = default_command

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = str(kwargs.get("command") or self.default_command)
        result = await self.sandbox.run(command, timeout_sec=self.timeout_sec)
        text = f"exit={result.exit_code} backend={result.backend}\n{result.combined}"
        return ToolResult(result.exit_code == 0, text)
