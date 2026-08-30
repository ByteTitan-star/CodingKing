"""Self-hosted Firecracker Micro-VM (Phase 4b).

Requires Linux + KVM + ``firecracker`` binary + kernel/rootfs images.
Guest command execution and workspace sync use SSH into the VM
(``CODERKING_FIRECRACKER_SSH_*``). Without those deps, ``available()`` is
False and ``create()`` fails closed with a clear RuntimeError.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from coderking_coding_agent.sandbox.base import ExecResult
from coderking_coding_agent.sandbox.credentials import is_secret_path
from coderking_coding_agent.workspace import SKIP_DIRS

log = logging.getLogger(__name__)

FIRECRACKER_REMOTE_ROOT = "/workspace"
DEFAULT_SSH_PORT = 2222


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 10.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


@dataclass(frozen=True)
class FirecrackerConfig:
    kernel: Path
    rootfs: Path
    binary: str
    ssh_host: str = "127.0.0.1"
    ssh_port: int = DEFAULT_SSH_PORT
    ssh_user: str = "root"
    ssh_key: Path | None = None
    memory_mb: int = 512
    vcpus: int = 1
    boot_args: str = "console=ttyS0 reboot=k panic=1 pci=off"

    @classmethod
    def from_env(
        cls,
        *,
        memory_mb: int = 512,
        vcpus: int = 1,
    ) -> FirecrackerConfig:
        kernel = Path(os.environ.get("CODERKING_FIRECRACKER_KERNEL", "")).expanduser()
        rootfs = Path(os.environ.get("CODERKING_FIRECRACKER_ROOTFS", "")).expanduser()
        binary = os.environ.get("CODERKING_FIRECRACKER_BIN", "firecracker").strip() or "firecracker"
        ssh_key_raw = os.environ.get("CODERKING_FIRECRACKER_SSH_KEY", "").strip()
        ssh_key = Path(ssh_key_raw).expanduser() if ssh_key_raw else None
        port_raw = os.environ.get("CODERKING_FIRECRACKER_SSH_PORT", str(DEFAULT_SSH_PORT))
        try:
            ssh_port = int(port_raw)
        except ValueError:
            ssh_port = DEFAULT_SSH_PORT
        return cls(
            kernel=kernel,
            rootfs=rootfs,
            binary=binary,
            ssh_host=os.environ.get("CODERKING_FIRECRACKER_SSH_HOST", "127.0.0.1").strip()
            or "127.0.0.1",
            ssh_port=ssh_port,
            ssh_user=os.environ.get("CODERKING_FIRECRACKER_SSH_USER", "root").strip() or "root",
            ssh_key=ssh_key,
            memory_mb=memory_mb,
            vcpus=max(1, vcpus),
        )


def firecracker_missing_deps(config: FirecrackerConfig) -> list[str]:
    """Return human-readable reasons Firecracker cannot run on this host."""
    missing: list[str] = []
    if os.name != "posix" or not hasattr(os, "uname"):
        missing.append("Linux host required")
    else:
        try:
            if os.uname().sysname.lower() != "linux":
                missing.append("Linux host required")
        except AttributeError:
            missing.append("Linux host required")
    if not Path("/dev/kvm").exists():
        missing.append("/dev/kvm not found (KVM required)")
    binary = config.binary if Path(config.binary).is_file() else shutil.which(config.binary)
    if not binary:
        missing.append(
            "firecracker binary not found "
            "(install firecracker or set CODERKING_FIRECRACKER_BIN)"
        )
    if not config.kernel.is_file():
        missing.append("CODERKING_FIRECRACKER_KERNEL must point to a kernel image")
    if not config.rootfs.is_file():
        missing.append("CODERKING_FIRECRACKER_ROOTFS must point to a rootfs image")
    if shutil.which("ssh") is None:
        missing.append("ssh client not found (required for guest exec / workspace sync)")
    return missing


def _api_put(socket_path: Path, path: str, body: dict[str, object]) -> None:
    conn = _UnixHTTPConnection(str(socket_path))
    try:
        payload = json.dumps(body).encode("utf-8")
        conn.request(
            "PUT",
            path,
            body=payload,
            headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
        )
        resp = conn.getresponse()
        data = resp.read()
        if resp.status >= 300:
            raise RuntimeError(
                f"Firecracker API PUT {path} failed: HTTP {resp.status} "
                f"{data.decode('utf-8', errors='replace')[:300]}"
            )
    finally:
        conn.close()


def configure_and_start_vm(socket_path: Path, config: FirecrackerConfig) -> None:
    """Drive the Firecracker HTTP API to boot a microVM."""
    _api_put(
        socket_path,
        "/machine-config",
        {"vcpu_count": config.vcpus, "mem_size_mib": config.memory_mb, "smt": False},
    )
    _api_put(
        socket_path,
        "/boot-source",
        {
            "kernel_image_path": str(config.kernel.resolve()),
            "boot_args": config.boot_args,
        },
    )
    _api_put(
        socket_path,
        "/drives/rootfs",
        {
            "drive_id": "rootfs",
            "path_on_host": str(config.rootfs.resolve()),
            "is_root_device": True,
            "is_read_only": False,
        },
    )
    _api_put(socket_path, "/actions", {"action_type": "InstanceStart"})


def iter_workspace_sync_files(workspace: Path) -> list[tuple[Path, str]]:
    root = workspace.resolve()
    out: list[tuple[Path, str]] = []
    if not root.is_dir():
        raise RuntimeError(f"Firecracker workspace sync requires a directory: {root}")
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


def sync_workspace_over_ssh(
    workspace: Path,
    config: FirecrackerConfig,
    *,
    remote_root: str = FIRECRACKER_REMOTE_ROOT,
) -> int:
    """Copy workspace files into the guest via scp. Fail closed on errors."""
    if shutil.which("scp") is None:
        raise RuntimeError("scp not found; required for Firecracker workspace sync")
    uploaded = 0
    for local, rel in iter_workspace_sync_files(workspace):
        remote = f"{remote_root.rstrip('/')}/{rel}"
        remote_dir = str(Path(remote).parent).replace("\\", "/")
        mkdir = _ssh_argv(config, f"mkdir -p {remote_dir}")
        scp = _scp_argv(config, str(local), f"{config.ssh_user}@{config.ssh_host}:{remote}")
        for argv in (mkdir, scp):
            proc = subprocess.run(argv, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()
                raise RuntimeError(
                    f"Firecracker workspace sync failed for {rel}: {err or proc.returncode}"
                )
        uploaded += 1
    log.info("Firecracker workspace sync uploaded %s files to %s", uploaded, remote_root)
    return uploaded


def _ssh_base_argv(config: FirecrackerConfig) -> list[str]:
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-p",
        str(config.ssh_port),
    ]
    if config.ssh_key is not None:
        argv.extend(["-i", str(config.ssh_key)])
    return argv


def _ssh_argv(config: FirecrackerConfig, remote_command: str) -> list[str]:
    return [*_ssh_base_argv(config), f"{config.ssh_user}@{config.ssh_host}", remote_command]


def _scp_argv(config: FirecrackerConfig, local: str, remote_spec: str) -> list[str]:
    argv = [
        "scp",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-P",
        str(config.ssh_port),
    ]
    if config.ssh_key is not None:
        argv.extend(["-i", str(config.ssh_key)])
    argv.extend([local, remote_spec])
    return argv


def wait_for_ssh(config: FirecrackerConfig, *, timeout_sec: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_sec
    last_err = ""
    while time.monotonic() < deadline:
        probe = subprocess.run(
            _ssh_argv(config, "true"),
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0:
            return
        last_err = (probe.stderr or probe.stdout or "").strip()
        time.sleep(1.0)
    raise RuntimeError(
        f"Firecracker guest SSH not ready at {config.ssh_host}:{config.ssh_port}: {last_err}"
    )


class FirecrackerSession:
    """Booted Firecracker microVM session (exec + sync via SSH)."""

    def __init__(
        self,
        *,
        proc: asyncio.subprocess.Process,
        socket_path: Path,
        work_dir: Path,
        workspace: Path,
        config: FirecrackerConfig,
        remote_root: str = FIRECRACKER_REMOTE_ROOT,
    ) -> None:
        self._proc = proc
        self._socket_path = socket_path
        self._work_dir = work_dir
        self.workspace = workspace
        self.config = config
        self.remote_root = remote_root
        self.backend_name = "microvm-firecracker"

    async def exec(self, command: str, *, timeout_sec: int) -> ExecResult:
        remote = f"cd {self.remote_root} && {command}"
        argv = _ssh_argv(self.config, remote)

        def _run() -> tuple[int, str, str]:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_sec,
            )
            return completed.returncode, completed.stdout or "", completed.stderr or ""

        try:
            code, out, err = await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout_sec + 5)
        except TimeoutError:
            return ExecResult(124, "", f"firecracker timeout after {timeout_sec}s", self.backend_name)
        except subprocess.TimeoutExpired:
            return ExecResult(124, "", f"firecracker timeout after {timeout_sec}s", self.backend_name)
        return ExecResult(code, out, err, self.backend_name)

    async def close(self) -> None:
        if self._proc.returncode is None:
            self._proc.kill()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except TimeoutError:
                pass
        if self._work_dir.exists():
            shutil.rmtree(self._work_dir, ignore_errors=True)


class FirecrackerProvider:
    """Self-hosted Firecracker Micro-VM provider (Phase 4b)."""

    name = "firecracker"

    def __init__(
        self,
        *,
        config: FirecrackerConfig | None = None,
        memory_mb: int = 512,
        vcpus: int = 1,
        ssh_wait_sec: float = 60.0,
    ) -> None:
        self.config = config or FirecrackerConfig.from_env(memory_mb=memory_mb, vcpus=vcpus)
        self.ssh_wait_sec = ssh_wait_sec

    def missing_deps(self) -> list[str]:
        return firecracker_missing_deps(self.config)

    async def available(self) -> bool:
        return not self.missing_deps()

    async def create(self, workspace: Path) -> FirecrackerSession:
        missing = self.missing_deps()
        if missing:
            raise RuntimeError(
                "Firecracker Micro-VM unavailable: "
                + "; ".join(missing)
                + ". Use sandbox_microvm_provider=mock or e2b, or set "
                "CODERKING_FIRECRACKER_KERNEL / ROOTFS / BIN / SSH_*."
            )

        root = workspace.resolve()
        work_dir = Path(tempfile.mkdtemp(prefix="coderking-fc-"))
        socket_path = work_dir / f"fc-{uuid4().hex[:8]}.sock"
        binary = (
            self.config.binary
            if Path(self.config.binary).is_file()
            else shutil.which(self.config.binary)
        )
        assert binary  # guarded by missing_deps

        proc = await asyncio.create_subprocess_exec(
            binary,
            "--api-sock",
            str(socket_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await _wait_for_api_socket(socket_path, proc, timeout_sec=10.0)
            await asyncio.to_thread(configure_and_start_vm, socket_path, self.config)
            await asyncio.to_thread(wait_for_ssh, self.config, timeout_sec=self.ssh_wait_sec)
            await asyncio.to_thread(sync_workspace_over_ssh, root, self.config)
        except Exception:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            shutil.rmtree(work_dir, ignore_errors=True)
            raise

        return FirecrackerSession(
            proc=proc,
            socket_path=socket_path,
            work_dir=work_dir,
            workspace=root,
            config=self.config,
        )


async def _wait_for_api_socket(
    socket_path: Path,
    proc: asyncio.subprocess.Process,
    *,
    timeout_sec: float,
) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if socket_path.exists():
            return
        if proc.returncode is not None:
            err = b""
            if proc.stderr is not None:
                err = await proc.stderr.read()
            raise RuntimeError(
                "Firecracker process exited before API socket was ready: "
                + err.decode("utf-8", errors="replace")[:400]
            )
        await asyncio.sleep(0.05)
    raise RuntimeError(f"Firecracker API socket not created: {socket_path}")
