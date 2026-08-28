"""Sandbox runner bridge for L2 dynamic tools."""

from __future__ import annotations

from coderking.sandbox.base import Sandbox


class SandboxToolRunner:
    def __init__(self, sandbox: Sandbox, *, timeout_sec: int) -> None:
        self.sandbox = sandbox
        self.timeout_sec = timeout_sec

    async def run(self, command: str, *, timeout_sec: int) -> tuple[int, str]:
        result = await self.sandbox.run(command, timeout_sec=timeout_sec or self.timeout_sec)
        return result.exit_code, result.combined
