"""Facade adapter: Settings → L2 SandboxFactoryConfig (#23)."""

from __future__ import annotations

from pathlib import Path

from coderking.config import Settings
from coderking_coding_agent.sandbox.cow import CowWorkspace
from coderking_coding_agent.sandbox.manager import create_sandbox as l2_create_sandbox
from coderking_coding_agent.sandbox.types import SandboxFactoryConfig


def _to_factory_config(settings: Settings) -> SandboxFactoryConfig:
    return SandboxFactoryConfig(
        sandbox_mode=settings.sandbox_mode,
        sandbox_image=settings.sandbox_image,
        sandbox_memory_mb=settings.sandbox_memory_mb,
        sandbox_cpus=settings.sandbox_cpus,
        sandbox_network=settings.sandbox_network,
        sandbox_network_mode=settings.sandbox_network_mode,
        sandbox_allow_hosts=tuple(settings.sandbox_allow_hosts),
        sandbox_microvm_provider=settings.sandbox_microvm_provider,
        sandbox_e2b_api_key=settings.sandbox_e2b_api_key,
        sandbox_e2b_template=settings.sandbox_e2b_template,
    )


async def create_sandbox(
    workspace: Path,
    settings: Settings,
    *,
    cow: CowWorkspace | None = None,
):
    return await l2_create_sandbox(workspace, _to_factory_config(settings), cow=cow)


__all__ = ["create_sandbox"]
