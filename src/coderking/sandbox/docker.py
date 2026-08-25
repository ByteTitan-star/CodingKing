from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from uuid import uuid4

from coderking.runtime.cancel import CancellationToken, CancelledTask
from coderking.sandbox.base import ExecResult, Sandbox
from coderking.sandbox.local import _communicate, _kill


async def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "info",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=3)
    except TimeoutError:
        proc.kill()
        return False
    return proc.returncode == 0


class DockerSandbox(Sandbox):
    name = "docker"

    def __init__(
        self,
        workspace: Path,
        *,
        image: str,
        memory_mb: int,
        cpus: float,
        network: bool,
        cancel: CancellationToken | None = None,
    ):
        self.workspace = workspace
        self.image = image
        self.memory_mb = memory_mb
        self.cpus = cpus
        self.network = network
        self.cancel = cancel
        self.last_args: list[str] = []
        self.last_container: str | None = None

    def build_args(self, command: str, container: str) -> list[str]:
        args = [
            "docker",
            "run",
            "--name",
            container,
            "--cpus",
            str(self.cpus),
            "--memory",
            f"{self.memory_mb}m",
            "-v",
            f"{self.workspace.resolve()}:/workspace",
            "-w",
            "/workspace",
        ]
        if not self.network:
            args.extend(["--network", "none"])
        args.extend([self.image, "sh", "-lc", command])
        return args

    async def run(self, command: str, *, timeout_sec: int) -> ExecResult:
        if self.cancel:
            self.cancel.raise_if_cancelled()
        container = f"coderking-{uuid4().hex[:12]}"
        self.last_container = container
        args = self.build_args(command, container)
        self.last_args = args
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await _communicate(proc, timeout_sec, self.cancel)
        except CancelledTask:
            _kill(proc)
            await _rm_container(container)
            raise
        except TimeoutError:
            _kill(proc)
            await _rm_container(container)
            return ExecResult(124, "", f"docker timeout after {timeout_sec}s", self.name)
        await _rm_container(container)
        return ExecResult(
            proc.returncode or 0,
            stdout_b.decode("utf-8", errors="replace"),
            stderr_b.decode("utf-8", errors="replace"),
            self.name,
        )


async def _rm_container(name: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "rm",
        "-f",
        name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
