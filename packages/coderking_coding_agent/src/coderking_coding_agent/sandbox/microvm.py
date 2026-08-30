"""Micro-VM sandbox: pluggable providers (mock / E2B / Firecracker)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from coderking_coding_agent.sandbox.base import ExecResult, Sandbox
from coderking_coding_agent.sandbox.credentials import is_secret_env_name, is_secret_path
from coderking_coding_agent.sandbox.docker import docker_available
from coderking_coding_agent.sandbox.firecracker import (
    FIRECRACKER_REMOTE_ROOT,
    FirecrackerConfig,
    FirecrackerProvider,
    FirecrackerSession,
    configure_and_start_vm,
    firecracker_missing_deps,
    sync_workspace_over_ssh,
)
from coderking_coding_agent.sandbox.local import _communicate, _kill
from coderking_coding_agent.workspace import SKIP_DIRS

MicroVmProviderName = Literal["mock", "e2b", "firecracker"]

FAKE_PASSWD = "root:x:0:0:CoderKing-MicroVM:/root:/bin/sh\n"
E2B_REMOTE_ROOT = "/home/user/workspace"
# Refuse single-file uploads larger than this to avoid silent hangs / cost spikes.
E2B_MAX_SYNC_FILE_BYTES = 5 * 1024 * 1024

log = logging.getLogger(__name__)

__all__ = [
    "E2B_REMOTE_ROOT",
    "E2BProvider",
    "E2BSession",
    "FIRECRACKER_REMOTE_ROOT",
    "FAKE_PASSWD",
    "FirecrackerConfig",
    "FirecrackerProvider",
    "FirecrackerSession",
    "MicroVmProvider",
    "MicroVmProviderName",
    "MicroVmSandbox",
    "MicroVmSession",
    "MockMicroVmProvider",
    "configure_and_start_vm",
    "create_microvm_provider",
    "firecracker_missing_deps",
    "iter_workspace_sync_files",
    "sync_workspace_over_ssh",
    "sync_workspace_to_e2b",
]


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


def iter_workspace_sync_files(workspace: Path) -> list[tuple[Path, str]]:
    """Local files to upload into a remote Micro-VM (skip secrets / SKIP_DIRS)."""
    root = workspace.resolve()
    out: list[tuple[Path, str]] = []
    if not root.is_dir():
        raise RuntimeError(f"E2B workspace sync requires a directory: {root}")
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        rel_posix = rel.as_posix()
        if is_secret_path(rel_posix):
            continue
        out.append((path, rel_posix))
    return out


def _write_remote_file(sandbox: object, remote_path: str, data: bytes) -> None:
    files = getattr(sandbox, "files", None)
    if files is not None and hasattr(files, "write"):
        files.write(remote_path, data)
        return
    fs = getattr(sandbox, "filesystem", None)
    if fs is not None and hasattr(fs, "write"):
        fs.write(remote_path, data)
        return
    raise RuntimeError("E2B sandbox has no files.write / filesystem.write API")


def sync_workspace_to_e2b(
    sandbox: object,
    workspace: Path,
    *,
    remote_root: str = E2B_REMOTE_ROOT,
    max_file_bytes: int = E2B_MAX_SYNC_FILE_BYTES,
) -> int:
    """Upload workspace into the E2B sandbox. Fail closed on any I/O or SDK error.

    Returns the number of files written.
    """
    uploaded = 0
    for local, rel in iter_workspace_sync_files(workspace):
        remote = f"{remote_root.rstrip('/')}/{rel}"
        try:
            data = local.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"E2B workspace sync failed reading {rel}: {exc}") from exc
        if len(data) > max_file_bytes:
            raise RuntimeError(
                f"E2B workspace sync refused oversized file {rel} ({len(data)} bytes; "
                f"limit {max_file_bytes})"
            )
        try:
            _write_remote_file(sandbox, remote, data)
        except Exception as exc:
            raise RuntimeError(f"E2B workspace sync failed uploading {rel}: {exc}") from exc
        uploaded += 1
    log.info("E2B workspace sync uploaded %s files to %s", uploaded, remote_root)
    return uploaded


def _kill_e2b_sandbox(sandbox: object) -> None:
    for meth in ("kill", "close"):
        fn = getattr(sandbox, meth, None)
        if callable(fn):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
            return


class E2BSession:
    """Thin E2B code-interpreter session wrapper."""

    def __init__(
        self,
        sandbox: object,
        workspace: Path,
        *,
        remote_root: str = E2B_REMOTE_ROOT,
    ) -> None:
        self._sandbox = sandbox
        self.workspace = workspace
        self.remote_root = remote_root
        self.backend_name = "microvm-e2b"

    async def exec(self, command: str, *, timeout_sec: int) -> ExecResult:
        # E2B SDK is sync in older versions; run in thread.
        remote_root = self.remote_root

        def _run() -> tuple[int, str, str]:
            sb = self._sandbox
            # Prefer commands.run if present (e2b_code_interpreter / e2b SDK).
            if hasattr(sb, "commands") and hasattr(sb.commands, "run"):
                run_fn = sb.commands.run
                try:
                    result = run_fn(command, timeout=timeout_sec, cwd=remote_root)
                except TypeError:
                    # Older SDKs may not accept cwd — fall back to shell cd.
                    wrapped = f"cd {remote_root!s} && {command}"
                    result = run_fn(wrapped, timeout=timeout_sec)
                exit_code = int(getattr(result, "exit_code", 0) or 0)
                stdout = str(getattr(result, "stdout", "") or "")
                stderr = str(getattr(result, "stderr", "") or "")
                return exit_code, stdout, stderr
            if hasattr(sb, "run_code"):
                code = (
                    "import os, subprocess, sys\n"
                    f"os.chdir({remote_root!r})\n"
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
        await asyncio.to_thread(_kill_e2b_sandbox, self._sandbox)


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

        root = workspace.resolve()

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
        try:
            await asyncio.to_thread(sync_workspace_to_e2b, sb, root)
        except Exception:
            await asyncio.to_thread(_kill_e2b_sandbox, sb)
            raise
        return E2BSession(sb, root, remote_root=E2B_REMOTE_ROOT)


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
        return FirecrackerProvider(memory_mb=memory_mb, vcpus=max(1, int(cpus)))
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
