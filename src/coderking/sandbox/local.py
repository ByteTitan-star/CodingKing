from __future__ import annotations

import asyncio
from pathlib import Path

from coderking.runtime.cancel import CancellationToken, CancelledTask
from coderking.sandbox.base import ExecResult, Sandbox
from coderking.sandbox.job_manager import JobManager, JobSnapshot


class LocalProcessSandbox(Sandbox):
    """Development fallback. Not a strong isolation boundary."""

    name = "local"

    def __init__(self, workspace: Path, cancel: CancellationToken | None = None):
        self.workspace = workspace
        self.cancel = cancel
        self._jobs = JobManager(workspace, cancel=cancel)

    async def start_job(self, command: str) -> str:
        return await self._jobs.start(command)

    def poll_job(self, job_id: str) -> JobSnapshot:
        return self._jobs.poll(job_id)

    async def kill_job(self, job_id: str) -> bool:
        return await self._jobs.kill(job_id)

    async def kill_all_jobs(self) -> None:
        await self._jobs.kill_all()

    async def run(self, command: str, *, timeout_sec: int) -> ExecResult:
        if self.cancel:
            self.cancel.raise_if_cancelled()
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=self.workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await _communicate(proc, timeout_sec, self.cancel)
        except CancelledTask:
            _kill(proc)
            await proc.wait()
            raise
        except TimeoutError:
            _kill(proc)
            await proc.wait()
            return ExecResult(124, "", f"timeout after {timeout_sec}s", self.name)
        return ExecResult(
            proc.returncode or 0,
            stdout_b.decode("utf-8", errors="replace"),
            stderr_b.decode("utf-8", errors="replace"),
            self.name,
        )


def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        proc.kill()


async def _communicate(
    proc: asyncio.subprocess.Process,
    timeout_sec: int,
    cancel: CancellationToken | None,
) -> tuple[bytes, bytes]:
    comm = asyncio.ensure_future(proc.communicate())
    tasks = {comm}
    watcher = None
    if cancel is not None:
        watcher = asyncio.ensure_future(cancel.wait())
        tasks.add(watcher)
    done, pending = await asyncio.wait(
        tasks, timeout=timeout_sec, return_when=asyncio.FIRST_COMPLETED
    )
    if comm in done:
        if watcher:
            watcher.cancel()
        return comm.result()
    for item in pending:
        item.cancel()
    if cancel is not None and cancel.cancelled:
        raise CancelledTask("task interrupted")
    raise TimeoutError
