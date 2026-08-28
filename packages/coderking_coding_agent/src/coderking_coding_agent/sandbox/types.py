"""Sandbox factory config — Settings-free for L2 boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SandboxMode = Literal["auto", "docker", "local", "microvm"]
NetworkMode = Literal["none", "full", "restricted"]
MicroVmProviderName = Literal["mock", "e2b", "firecracker"]


@dataclass(frozen=True)
class SandboxFactoryConfig:
    sandbox_mode: SandboxMode = "auto"
    sandbox_image: str = "python:3.12-slim"
    sandbox_memory_mb: int = 2048
    sandbox_cpus: float = 2.0
    sandbox_network: bool = False
    sandbox_network_mode: NetworkMode | None = None
    sandbox_allow_hosts: tuple[str, ...] = ()
    sandbox_microvm_provider: MicroVmProviderName = "mock"
    sandbox_e2b_api_key: str = ""
    sandbox_e2b_template: str | None = None
