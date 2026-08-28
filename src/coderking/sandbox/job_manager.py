"""Background shell jobs for long-running commands (Pi-style bash poll)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from coderking.runtime.cancel import CancellationToken

MAX_BUFFER_BYTES = 1_048_576
DEFAULT_TTL_SEC = 3600
TAIL_CHARS = 8192


@dataclass
class JobSnapshot:
    job_id: str
    status: str
    stdout_tail: str
    stderr_tail: str
    exit_code: int | None = None


class _RingBuffer:
    def __init__(self, max_bytes: int) -> None:
        self._max = max_bytes
        self._data = bytearray()

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._data.extend(chunk)
        if len(self._data) > self._max:
            self._data = self._data[-self._max :]

    def tail(self, chars: int = TAIL_CHARS) -> str:
        text = self._data.decode("utf-8", errors="replace")
        if len(text) <= chars:
            return text
        return text[-chars:]


@dataclass
class _Job:
    job_id: str
    command: str
    proc: asyncio.subprocess.Process
    stdout: _RingBuffer
    stderr: _RingBuffer
    started_at: float
    status: str = "running"
    exit_code: int | None = None
    readers: list[asyncio.Task[None]] | None = None


class JobManager:
    def __init__(
        self,
        workspace: Path,
        *,
        cancel: CancellationToken | None = None,
        ttl_sec: int = DEFAULT_TTL_SEC,
    ) -> None:
        self.workspace = workspace
        self.cancel = cancel
        self.ttl_sec = ttl_sec
        self._jobs: dict[str, _Job] = {}

    async def start(self, command: str) -> str:
        self._cleanup_expired()
        if self.cancel:
            self.cancel.raise_if_cancelled()
        job_id = uuid4().hex[:12]
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=self.workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        job = _Job(
            job_id=job_id,
            command=command,
            proc=proc,
            stdout=_RingBuffer(MAX_BUFFER_BYTES),
            stderr=_RingBuffer(MAX_BUFFER_BYTES),
            started_at=time.monotonic(),
        )
        job.readers = [
            asyncio.create_task(_read_stream(proc.stdout, job.stdout)),
            asyncio.create_task(_read_stream(proc.stderr, job.stderr)),
            asyncio.create_task(_watch_proc(job)),
        ]
        self._jobs[job_id] = job
        return job_id

    def poll(self, job_id: str) -> JobSnapshot:
        self._cleanup_expired()
        job = self._jobs.get(job_id)
        if job is None:
            return JobSnapshot(job_id, "unknown", "", "", None)
        self._refresh_status(job)
        return JobSnapshot(
            job_id=job.job_id,
            status=job.status,
            stdout_tail=job.stdout.tail(),
            stderr_tail=job.stderr.tail(),
            exit_code=job.exit_code,
        )

    async def kill(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        await _terminate_job(job)
        job.status = "killed"
        return True

    async def kill_all(self) -> None:
        for job_id in list(self._jobs):
            await self.kill(job_id)

    def _refresh_status(self, job: _Job) -> None:
        if job.status != "running":
            return
        code = job.proc.returncode
        if code is None:
            return
        job.exit_code = code
        job.status = "completed" if code == 0 else "failed"

    def _cleanup_expired(self) -> None:
        now = time.monotonic()
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if now - job.started_at > self.ttl_sec and job.status != "running"
        ]
        for job_id in expired:
            del self._jobs[job_id]


async def _read_stream(
    stream: asyncio.StreamReader | None,
    buffer: _RingBuffer,
) -> None:
    if stream is None:
        return
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        buffer.append(chunk)


async def _watch_proc(job: _Job) -> None:
    code = await job.proc.wait()
    job.exit_code = code
    if job.status == "running":
        job.status = "completed" if code == 0 else "failed"


async def _terminate_job(job: _Job) -> None:
    if job.proc.returncode is None:
        job.proc.kill()
        try:
            await asyncio.wait_for(job.proc.wait(), timeout=5)
        except TimeoutError:
            pass
    if job.readers:
        for task in job.readers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*job.readers, return_exceptions=True)
