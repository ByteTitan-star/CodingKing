from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SandboxMode = Literal["auto", "docker", "local"]
NetworkMode = Literal["none", "full", "restricted"]

YAML_KEYS = (
    "openai_base_url",
    "model",
    "disable_thinking",
    "sandbox_mode",
    "sandbox_timeout_sec",
    "sandbox_memory_mb",
    "sandbox_cpus",
    "sandbox_network",
    "sandbox_network_mode",
    "sandbox_allow_hosts",
    "sandbox_image",
    "sandbox_cow",
    "sandbox_rollback_on_interrupt",
    "max_iterations",
    "allow_commit",
)

ENV_MAP = {
    "openai_base_url": "CODERKING_OPENAI_BASE_URL",
    "openai_api_key": "CODERKING_OPENAI_API_KEY",
    "model": "CODERKING_MODEL",
    "disable_thinking": "CODERKING_DISABLE_THINKING",
    "sandbox_mode": "CODERKING_SANDBOX_MODE",
    "sandbox_timeout_sec": "CODERKING_SANDBOX_TIMEOUT_SEC",
    "sandbox_memory_mb": "CODERKING_SANDBOX_MEMORY_MB",
    "sandbox_cpus": "CODERKING_SANDBOX_CPUS",
    "sandbox_network": "CODERKING_SANDBOX_NETWORK",
    "sandbox_network_mode": "CODERKING_SANDBOX_NETWORK_MODE",
    "sandbox_allow_hosts": "CODERKING_SANDBOX_ALLOW_HOSTS",
    "sandbox_image": "CODERKING_SANDBOX_IMAGE",
    "sandbox_cow": "CODERKING_SANDBOX_COW",
    "sandbox_rollback_on_interrupt": "CODERKING_SANDBOX_ROLLBACK_ON_INTERRUPT",
    "max_iterations": "CODERKING_MAX_ITERATIONS",
    "allow_commit": "CODERKING_ALLOW_COMMIT",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    model: str = "gpt-4o-mini"
    disable_thinking: bool = True

    sandbox_mode: SandboxMode = "auto"
    sandbox_timeout_sec: int = 120
    sandbox_memory_mb: int = 512
    sandbox_cpus: float = 1.0
    sandbox_network: bool = False
    sandbox_network_mode: NetworkMode | None = None
    sandbox_allow_hosts: list[str] = Field(
        default_factory=lambda: [
            "pypi.org",
            "files.pythonhosted.org",
            "pypi.python.org",
            "registry.npmjs.org",
            "registry.yarnpkg.com",
            "github.com",
            "codeload.github.com",
            "objects.githubusercontent.com",
        ]
    )
    sandbox_image: str = "python:3.12-slim"
    sandbox_cow: bool = False
    sandbox_rollback_on_interrupt: bool = False

    max_iterations: int = 24
    allow_commit: bool = False
    extension: str = "swe"
    workspace: Path = Field(default_factory=lambda: Path.cwd())

    def resolved_workspace(self) -> Path:
        return self.workspace.expanduser().resolve()


def config_yaml_path(workspace: Path) -> Path:
    return workspace.resolve() / ".coderking" / "config.yaml"


def read_yaml_config(workspace: Path) -> dict[str, Any]:
    path = config_yaml_path(workspace)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: v for k, v in data.items() if k in YAML_KEYS and v is not None}


def write_yaml_config(workspace: Path, updates: dict[str, Any]) -> Path:
    path = config_yaml_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = read_yaml_config(workspace)
    for key, value in updates.items():
        if key == "openai_api_key":
            continue
        if key in YAML_KEYS and value is not None:
            current[key] = value
    path.write_text(yaml.safe_dump(current, sort_keys=False), encoding="utf-8")
    return path


def load_settings(workspace: Path | None = None, **overrides: object) -> Settings:
    root = (
        Path(str(overrides["workspace"])).resolve()
        if overrides.get("workspace")
        else (workspace.resolve() if workspace is not None else Path.cwd())
    )
    load_dotenv(root / ".env")
    load_dotenv(Path.cwd() / ".env")
    data: dict[str, Any] = {"workspace": root}
    data.update(read_yaml_config(root))
    for field, env_name in ENV_MAP.items():
        if env_name in os.environ and os.environ[env_name] != "":
            data[field] = os.environ[env_name]
    data.update({k: v for k, v in overrides.items() if v is not None})
    if isinstance(data.get("sandbox_allow_hosts"), str):
        from coderking.sandbox.network import parse_allow_hosts

        data["sandbox_allow_hosts"] = list(parse_allow_hosts(data["sandbox_allow_hosts"]))
    return Settings.model_validate(data)
