from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from coderking.sandbox.job_manager import JobSnapshot


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

    async def start_job(self, command: str) -> str:
        raise NotImplementedError(f"{self.name} sandbox does not support background jobs")

    def poll_job(self, job_id: str) -> JobSnapshot:
        raise NotImplementedError(f"{self.name} sandbox does not support background jobs")

    async def kill_job(self, job_id: str) -> bool:
        raise NotImplementedError(f"{self.name} sandbox does not support background jobs")

    async def kill_all_jobs(self) -> None:
        return None

    async def close(self) -> None:
        await self.kill_all_jobs()
