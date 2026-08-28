from __future__ import annotations

import json
import re
from typing import Any

from coderking.sandbox.base import Sandbox
from coderking.tools.base import Tool, ToolResult

DANGEROUS = re.compile(
    r"(rm\s+-rf\s+/)|(mkfs\b)|(dd\s+if=)|(shutdown\b)|(reboot\b)|(:\(\)\{)",
    re.I,
)


class ShellTool(Tool):
    description = (
        "Run a shell command inside the sandbox (cwd = workspace). "
        "Use background=true for long-running commands; poll with job_id; "
        "kill with job_id+kill=true."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "background": {
                "type": "boolean",
                "description": "Start command in background and return job_id",
            },
            "job_id": {
                "type": "string",
                "description": "Poll or kill an existing background job",
            },
            "kill": {
                "type": "boolean",
                "description": "Kill the background job identified by job_id",
            },
        },
    }

    def __init__(self, sandbox: Sandbox, timeout_sec: int, *, name: str = "shell"):
        self.name = name
        self.sandbox = sandbox
        self.timeout_sec = timeout_sec

    def needs_approval(self, command: str) -> bool:
        return bool(DANGEROUS.search(command))

    async def execute(self, **kwargs: Any) -> ToolResult:
        job_id = kwargs.get("job_id")
        if kwargs.get("kill"):
            if not job_id:
                return ToolResult(False, "job_id required when kill=true")
            killed = await self.sandbox.kill_job(str(job_id))
            if not killed:
                return ToolResult(False, f"unknown job: {job_id}")
            return ToolResult(True, f"job {job_id} killed")

        if job_id and not kwargs.get("command"):
            snapshot = self.sandbox.poll_job(str(job_id))
            payload = {
                "job_id": snapshot.job_id,
                "status": snapshot.status,
                "stdout_tail": snapshot.stdout_tail,
                "stderr_tail": snapshot.stderr_tail,
                "exit_code": snapshot.exit_code,
            }
            ok = snapshot.status != "unknown"
            return ToolResult(ok, json.dumps(payload, ensure_ascii=False))

        command = kwargs.get("command")
        if not command:
            return ToolResult(False, "command is required unless polling or killing a job")
        command = str(command)

        if kwargs.get("background"):
            try:
                started = await self.sandbox.start_job(command)
            except NotImplementedError:
                return ToolResult(False, "background jobs not supported by this sandbox")
            except Exception as exc:
                return ToolResult(False, f"failed to start background job: {exc}")
            return ToolResult(
                True,
                json.dumps({"job_id": started, "status": "running"}, ensure_ascii=False),
            )

        result = await self.sandbox.run(command, timeout_sec=self.timeout_sec)
        text = result.combined or "(no output)"
        prefix = f"exit={result.exit_code} backend={result.backend}\n"
        return ToolResult(result.exit_code == 0, prefix + text)
