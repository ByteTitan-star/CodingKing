from __future__ import annotations

from pathlib import Path

from coderking.config import Settings
from coderking.sandbox.base import Sandbox
from coderking.sandbox.docker import DockerSandbox, docker_available
from coderking.sandbox.local import LocalProcessSandbox


async def create_sandbox(workspace: Path, settings: Settings) -> tuple[Sandbox, str]:
    mode = settings.sandbox_mode
    if mode == "local":
        return LocalProcessSandbox(workspace), "development fallback (not strong isolation)"
    if mode == "docker":
        if not await docker_available():
            raise RuntimeError("CODERKING_SANDBOX_MODE=docker but Docker is unavailable")
        return _docker(workspace, settings), "docker"
    if await docker_available():
        return _docker(workspace, settings), "docker"
    return LocalProcessSandbox(workspace), "development fallback (not strong isolation)"


def _docker(workspace: Path, settings: Settings) -> DockerSandbox:
    return DockerSandbox(
        workspace,
        image=settings.sandbox_image,
        memory_mb=settings.sandbox_memory_mb,
        cpus=settings.sandbox_cpus,
        network=settings.sandbox_network,
    )
