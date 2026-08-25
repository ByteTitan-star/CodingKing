from __future__ import annotations

import re
from typing import Any

from coderking.sandbox.base import Sandbox
from coderking.tools.base import Tool, ToolResult

DANGEROUS = re.compile(
    r"(rm\s+-rf\s+/)|(mkfs\b)|(dd\s+if=)|(shutdown\b)|(reboot\b)|(:\(\)\{)",
    re.I,
)


class ShellTool(Tool):
    name = "shell"
    description = "Run a shell command inside the sandbox (cwd = workspace)."
    parameters = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    }

    def __init__(self, sandbox: Sandbox, timeout_sec: int):
        self.sandbox = sandbox
        self.timeout_sec = timeout_sec

    def needs_approval(self, command: str) -> bool:
        return bool(DANGEROUS.search(command))

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = str(kwargs["command"])
        result = await self.sandbox.run(command, timeout_sec=self.timeout_sec)
        text = result.combined or "(no output)"
        prefix = f"exit={result.exit_code} backend={result.backend}\n"
        return ToolResult(result.exit_code == 0, prefix + text)
