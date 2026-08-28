from __future__ import annotations

from pathlib import Path

from coderking.config import Settings
from coderking.sandbox.base import Sandbox
from coderking.sandbox.cow import CowWorkspace
from coderking.sandbox.docker import DockerSandbox, docker_available
from coderking.sandbox.local import LocalProcessSandbox
from coderking.sandbox.network import NetworkPolicy, resolve_network_mode


async def create_sandbox(
    workspace: Path,
    settings: Settings,
    *,
    cow: CowWorkspace | None = None,
) -> tuple[Sandbox, str]:
    work = cow.work_path if cow is not None and cow.active else workspace
    mode = settings.sandbox_mode
    note_suffix = " +cow" if cow is not None and cow.active else ""
    if mode == "local":
        return (
            LocalProcessSandbox(work),
            f"development fallback (not strong isolation){note_suffix}",
        )
    if mode == "docker":
        if not await docker_available():
            raise RuntimeError("CODERKING_SANDBOX_MODE=docker but Docker is unavailable")
        return _docker(work, settings), f"docker{note_suffix}"
    if await docker_available():
        return _docker(work, settings), f"docker{note_suffix}"
    return (
        LocalProcessSandbox(work),
        f"development fallback (not strong isolation){note_suffix}",
    )


def _network_policy(settings: Settings) -> NetworkPolicy:
    mode = resolve_network_mode(
        sandbox_network=settings.sandbox_network,
        sandbox_network_mode=settings.sandbox_network_mode,
    )
    hosts = tuple(settings.sandbox_allow_hosts)
    return NetworkPolicy(mode=mode, allow_hosts=hosts if mode == "restricted" else ())


def _docker(workspace: Path, settings: Settings) -> DockerSandbox:
    return DockerSandbox(
        workspace,
        image=settings.sandbox_image,
        memory_mb=settings.sandbox_memory_mb,
        cpus=settings.sandbox_cpus,
        network_policy=_network_policy(settings),
    )
