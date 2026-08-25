from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    backend: str

    @property
    def combined(self) -> str:
        parts = [self.stdout, self.stderr]
        return "\n".join(p for p in parts if p).strip()


class Sandbox(ABC):
    name: str

    @abstractmethod
    async def run(self, command: str, *, timeout_sec: int) -> ExecResult: ...

    async def close(self) -> None:
        return None
