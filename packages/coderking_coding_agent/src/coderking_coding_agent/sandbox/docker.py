from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from coderking_agent_core.cancel import CancellationToken, CancelledTask
from coderking_coding_agent.sandbox.base import ExecResult, Sandbox
from coderking_coding_agent.sandbox.credentials import is_secret_env_name
from coderking_coding_agent.sandbox.job_manager import JobSnapshot
from coderking_coding_agent.sandbox.local import _communicate, _kill
from coderking_coding_agent.sandbox.network import AllowlistProxy, NetworkPolicy

log = logging.getLogger(__name__)


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


def _docker_env_args(extra: dict[str, str] | None = None) -> list[str]:
    """Never inherit host env; only explicit extras + sandbox marker."""
    args: list[str] = ["--env", "CODERKING_SANDBOX=1"]
    for key, value in sorted((extra or {}).items()):
        if is_secret_env_name(key):
            continue
        args.extend(["--env", f"{key}={value}"])
    return args


class DockerSandbox(Sandbox):
    name = "docker"

    def __init__(
        self,
        workspace: Path,
        *,
        image: str,
        memory_mb: int,
        cpus: float,
        network: bool = False,
        network_policy: NetworkPolicy | None = None,
        cancel: CancellationToken | None = None,
    ):
        self.workspace = workspace
        self.image = image
        self.memory_mb = memory_mb
        self.cpus = cpus
        self.policy = network_policy or NetworkPolicy(mode="full" if network else "none")
        self.network = self.policy.mode != "none"  # legacy flag for tests
        self.cancel = cancel
        self.last_args: list[str] = []
        self.last_container: str | None = None
        self.last_denials: list[str] = []
        self._job_containers: dict[str, str] = {}
        self.policy.warn_if_best_effort()

    def build_args(
        self,
        command: str,
        container: str,
        *,
        proxy_url: str | None = None,
    ) -> list[str]:
        policy = self.policy.with_proxy_url(proxy_url) if proxy_url else self.policy
        extra_env = policy.proxy_env()
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
            *_docker_env_args(extra_env),
            *policy.docker_network_args(),
        ]
        if policy.needs_proxy:
            args.extend(["--add-host", "host.docker.internal:host-gateway"])
        args.extend([self.image, "sh", "-lc", command])
        return args

    def build_detached_args(
        self,
        command: str,
        container: str,
        *,
        proxy_url: str | None = None,
    ) -> list[str]:
        policy = self.policy.with_proxy_url(proxy_url) if proxy_url else self.policy
        extra_env = policy.proxy_env()
        args = [
            "docker",
            "run",
            "-d",
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
            *_docker_env_args(extra_env),
            *policy.docker_network_args(),
        ]
        if policy.needs_proxy:
            args.extend(["--add-host", "host.docker.internal:host-gateway"])
        args.extend([self.image, "sh", "-lc", command])
        return args

    async def _proxy_url_for_container(self) -> tuple[str | None, AllowlistProxy | None]:
        if not self.policy.needs_proxy:
            return None, None
        # Linux Docker host-gateway cannot reach a loopback-only bind; elsewhere
        # prefer 127.0.0.1. Auth token in the proxy URL blocks unauthorized reuse.
        bind_host = "0.0.0.0" if sys.platform.startswith("linux") else "127.0.0.1"
        proxy = AllowlistProxy(self.policy, host=bind_host)
        await proxy.start()
        assert proxy.port is not None
        url = proxy.proxy_url_for("host.docker.internal")
        return url, proxy

    async def start_job(self, command: str) -> str:
        if self.cancel:
            self.cancel.raise_if_cancelled()
        if self.policy.needs_proxy:
            raise RuntimeError(
                "background jobs are not supported with sandbox_network_mode=restricted"
            )
        job_id = uuid4().hex[:12]
        container = f"coderking-job-{job_id}"
        args = self.build_detached_args(command, container)
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        if proc.returncode != 0:
            err = stderr_b.decode("utf-8", errors="replace").strip()
            raise RuntimeError(err or "failed to start docker background job")
        self._job_containers[job_id] = container.strip()
        return job_id

    def poll_job(self, job_id: str) -> JobSnapshot:
        container = self._job_containers.get(job_id)
        if container is None:
            return JobSnapshot(job_id, "unknown", "", "", None)
        inspect = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}} {{.State.ExitCode}}",
                container,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        parts = inspect.stdout.strip().split()
        docker_status = parts[0] if parts else "unknown"
        exit_code: int | None = None
        if len(parts) > 1 and parts[1].lstrip("-").isdigit():
            exit_code = int(parts[1])
        logs = subprocess.run(
            ["docker", "logs", "--tail", "200", container],
            capture_output=True,
            text=True,
            check=False,
        )
        tail = logs.stdout or logs.stderr or ""
        if docker_status == "running":
            status = "running"
        elif exit_code == 0:
            status = "completed"
        else:
            status = "failed"
        return JobSnapshot(job_id, status, tail, "", exit_code)

    async def kill_job(self, job_id: str) -> bool:
        container = self._job_containers.pop(job_id, None)
        if container is None:
            return False
        await _rm_container(container)
        return True

    async def kill_all_jobs(self) -> None:
        for job_id in list(self._job_containers):
            await self.kill_job(job_id)

    async def run(self, command: str, *, timeout_sec: int) -> ExecResult:
        if self.cancel:
            self.cancel.raise_if_cancelled()
        container = f"coderking-{uuid4().hex[:12]}"
        self.last_container = container
        proxy_url, proxy = await self._proxy_url_for_container()
        try:
            args = self.build_args(command, container, proxy_url=proxy_url)
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
            if proxy is not None:
                self.last_denials = list(proxy.denials)
            return ExecResult(
                proc.returncode or 0,
                stdout_b.decode("utf-8", errors="replace"),
                stderr_b.decode("utf-8", errors="replace"),
                self.name,
            )
        finally:
            if proxy is not None:
                await proxy.stop()


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
