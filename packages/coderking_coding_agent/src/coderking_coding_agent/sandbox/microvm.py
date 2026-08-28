"""Micro-VM sandbox: pluggable providers (mock / E2B / Firecracker stub)."""

from __future__ import annotations

import asyncio
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from coderking_coding_agent.sandbox.base import ExecResult, Sandbox
from coderking_coding_agent.sandbox.credentials import is_secret_env_name
from coderking_coding_agent.sandbox.docker import docker_available
from coderking_coding_agent.sandbox.local import _communicate, _kill

MicroVmProviderName = Literal["mock", "e2b", "firecracker"]

FAKE_PASSWD = "root:x:0:0:CoderKing-MicroVM:/root:/bin/sh\n"


class MicroVmSession(Protocol):
    async def exec(self, command: str, *, timeout_sec: int) -> ExecResult: ...

    async def close(self) -> None: ...


class MicroVmProvider(Protocol):
    name: str

    async def available(self) -> bool: ...

    async def create(self, workspace: Path) -> MicroVmSession: ...


@dataclass
class _DockerSealedSession:
    """Docker-backed sealed root: host /etc/passwd is never mounted."""

    workspace: Path
    sealed_root: Path
    image: str
    memory_mb: int
    cpus: float
    container_prefix: str = "coderking-mvm"
    backend_name: str = "microvm-mock"

    async def exec(self, command: str, *, timeout_sec: int) -> ExecResult:
        container = f"{self.container_prefix}-{uuid4().hex[:10]}"
        passwd_file = self.sealed_root / "etc" / "passwd"
        args = [
            "docker",
            "run",
            "--name",
            container,
            "--cpus",
            str(self.cpus),
            "--memory",
            f"{self.memory_mb}m",
            "--network",
            "none",
            "-v",
            f"{self.workspace.resolve()}:/workspace",
            "-v",
            f"{passwd_file.resolve()}:/etc/passwd:ro",
            "-w",
            "/workspace",
            "--env",
            "CODERKING_SANDBOX=1",
            "--env",
            "CODERKING_MICROVM=1",
            self.image,
            "sh",
            "-lc",
            command,
        ]
        # Drop any accidental secret-looking env from docker CLI inheritance: none passed.
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_minimal_docker_host_env(),
        )
        try:
            stdout_b, stderr_b = await _communicate(proc, timeout_sec, None)
        except TimeoutError:
            _kill(proc)
            await _rm_container(container)
            return ExecResult(124, "", f"microvm timeout after {timeout_sec}s", self.backend_name)
        await _rm_container(container)
        return ExecResult(
            proc.returncode or 0,
            stdout_b.decode("utf-8", errors="replace"),
            stderr_b.decode("utf-8", errors="replace"),
            self.backend_name,
        )

    async def close(self) -> None:
        if self.sealed_root.exists():
            shutil.rmtree(self.sealed_root, ignore_errors=True)


class MockMicroVmProvider:
    """Phase-4a stand-in: Docker sealed mounts (host passwd not visible)."""

    name = "mock"

    def __init__(
        self,
        *,
        image: str = "python:3.12-slim",
        memory_mb: int = 512,
        cpus: float = 1.0,
    ) -> None:
        self.image = image
        self.memory_mb = memory_mb
        self.cpus = cpus

    async def available(self) -> bool:
        return await docker_available()

    async def create(self, workspace: Path) -> _DockerSealedSession:
        if not await self.available():
            raise RuntimeError(
                "mock microvm provider requires Docker "
                "(set CODERKING_SANDBOX_MICROVM_PROVIDER=e2b for hosted VMs)"
            )
        sealed = workspace.resolve() / ".coderking" / "microvm" / uuid4().hex[:12]
        (sealed / "etc").mkdir(parents=True, exist_ok=True)
        (sealed / "etc" / "passwd").write_text(FAKE_PASSWD, encoding="utf-8")
        return _DockerSealedSession(
            workspace=workspace.resolve(),
            sealed_root=sealed,
            image=self.image,
            memory_mb=self.memory_mb,
            cpus=self.cpus,
        )


class FirecrackerProvider:
    """Self-hosted Firecracker — Phase 4b placeholder."""

    name = "firecracker"

    async def available(self) -> bool:
        return False

    async def create(self, workspace: Path) -> MicroVmSession:
        raise NotImplementedError(
            "Firecracker self-hosted Micro-VM is Phase 4b; "
            "use sandbox_microvm_provider=mock (Docker sealed) or e2b"
        )


class E2BSession:
    """Thin E2B code-interpreter session wrapper."""

    def __init__(self, sandbox: object, workspace: Path) -> None:
        self._sandbox = sandbox
        self.workspace = workspace
        self.backend_name = "microvm-e2b"

    async def exec(self, command: str, *, timeout_sec: int) -> ExecResult:
        # E2B SDK is sync in older versions; run in thread.
        def _run() -> tuple[int, str, str]:
            sb = self._sandbox
            # Prefer commands.run if present (e2b_code_interpreter / e2b SDK).
            if hasattr(sb, "commands") and hasattr(sb.commands, "run"):
                result = sb.commands.run(command, timeout=timeout_sec)
                exit_code = int(getattr(result, "exit_code", 0) or 0)
                stdout = str(getattr(result, "stdout", "") or "")
                stderr = str(getattr(result, "stderr", "") or "")
                return exit_code, stdout, stderr
            if hasattr(sb, "run_code"):
                code = (
                    "import subprocess, sys\n"
                    f"r = subprocess.run({command!r}, shell=True, "
                    "capture_output=True, text=True)\n"
                    "sys.stdout.write(r.stdout)\n"
                    "sys.stderr.write(r.stderr)\n"
                    "raise SystemExit(r.returncode)\n"
                )
                result = sb.run_code(code)
                return 0, str(getattr(result, "text", "") or ""), ""
            raise RuntimeError("unsupported E2B sandbox SDK surface")

        try:
            exit_code, stdout, stderr = await asyncio.wait_for(
                asyncio.to_thread(_run), timeout=timeout_sec + 5
            )
        except TimeoutError:
            return ExecResult(124, "", f"e2b timeout after {timeout_sec}s", self.backend_name)
        return ExecResult(exit_code, stdout, stderr, self.backend_name)

    async def close(self) -> None:
        sb = self._sandbox

        def _kill() -> None:
            for meth in ("kill", "close"):
                fn = getattr(sb, meth, None)
                if callable(fn):
                    fn()
                    return

        await asyncio.to_thread(_kill)


class E2BProvider:
    """Hosted Micro-VM via E2B (optional dependency)."""

    name = "e2b"

    def __init__(self, *, api_key: str, template: str | None = None) -> None:
        if not api_key:
            raise ValueError(
                "E2B microvm requires an API key (CODERKING_E2B_API_KEY or sandbox_e2b_api_key)"
            )
        self.api_key = api_key
        self.template = template

    async def available(self) -> bool:
        try:
            import e2b  # noqa: F401
        except ImportError:
            try:
                import e2b_code_interpreter  # noqa: F401
            except ImportError:
                return False
        return True

    async def create(self, workspace: Path) -> E2BSession:
        if not await self.available():
            raise RuntimeError("E2B SDK not installed; pip install e2b or e2b-code-interpreter")

        def _create() -> object:
            try:
                from e2b_code_interpreter import Sandbox as E2BSandbox
            except ImportError:
                from e2b import Sandbox as E2BSandbox  # type: ignore[no-redef]
            kwargs: dict[str, object] = {"api_key": self.api_key}
            if self.template:
                kwargs["template"] = self.template
            return E2BSandbox.create(**kwargs)

        sb = await asyncio.to_thread(_create)
        return E2BSession(sb, workspace.resolve())


class MicroVmSandbox(Sandbox):
    name = "microvm"

    def __init__(
        self,
        workspace: Path,
        *,
        provider: MicroVmProvider,
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self._session: MicroVmSession | None = None
        self.cold_start_sec: float | None = None

    async def ensure_started(self) -> float:
        if self._session is not None and self.cold_start_sec is not None:
            return self.cold_start_sec
        t0 = time.perf_counter()
        self._session = await self.provider.create(self.workspace)
        self.cold_start_sec = time.perf_counter() - t0
        return self.cold_start_sec

    async def run(self, command: str, *, timeout_sec: int) -> ExecResult:
        await self.ensure_started()
        assert self._session is not None
        return await self._session.exec(command, timeout_sec=timeout_sec)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None


def create_microvm_provider(
    name: MicroVmProviderName,
    *,
    api_key: str = "",
    template: str | None = None,
    image: str = "python:3.12-slim",
    memory_mb: int = 512,
    cpus: float = 1.0,
) -> MicroVmProvider:
    if name == "mock":
        return MockMicroVmProvider(image=image, memory_mb=memory_mb, cpus=cpus)
    if name == "e2b":
        return E2BProvider(api_key=api_key, template=template)
    if name == "firecracker":
        return FirecrackerProvider()
    raise ValueError(f"unknown microvm provider: {name}")


def _minimal_docker_host_env() -> dict[str, str]:
    """Host env for invoking docker CLI — strip provider secrets."""
    import os

    out: dict[str, str] = {}
    for key, value in os.environ.items():
        if is_secret_env_name(key):
            continue
        out[key] = value
    return out


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
