"""Load `.coderking/mcp.json` server definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class McpConfig:
    servers: tuple[McpServerConfig, ...] = ()
    allowlist: tuple[str, ...] = ()

    def selected(self) -> list[McpServerConfig]:
        enabled = [s for s in self.servers if s.enabled]
        if not self.allowlist:
            return enabled
        allowed = set(self.allowlist)
        return [s for s in enabled if s.name in allowed]


def mcp_config_path(workspace: Path) -> Path:
    return workspace.resolve() / ".coderking" / "mcp.json"


def load_mcp_config(workspace: Path) -> McpConfig:
    path = mcp_config_path(workspace)
    if not path.is_file():
        return McpConfig()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"invalid MCP config (expected object): {path}")
    allowlist = tuple(str(x) for x in (raw.get("allowlist") or []) if str(x).strip())
    servers_raw = raw.get("mcpServers") or raw.get("servers") or {}
    if not isinstance(servers_raw, dict):
        raise ValueError(f"invalid mcpServers in {path}")
    servers: list[McpServerConfig] = []
    for name, spec in servers_raw.items():
        if not isinstance(spec, dict):
            continue
        command = str(spec.get("command") or "").strip()
        if not command:
            raise ValueError(f"MCP server {name!r} missing command")
        args = tuple(str(a) for a in (spec.get("args") or []))
        env = {str(k): str(v) for k, v in dict(spec.get("env") or {}).items()}
        enabled = bool(spec.get("enabled", True))
        servers.append(
            McpServerConfig(
                name=str(name),
                command=command,
                args=args,
                env=env,
                enabled=enabled,
            )
        )
    return McpConfig(servers=tuple(servers), allowlist=allowlist)


def dump_example_config() -> dict[str, Any]:
    return {
        "allowlist": ["demo"],
        "mcpServers": {
            "demo": {
                "command": "python",
                "args": ["-m", "coderking.mcp.mock_server"],
                "enabled": True,
            }
        },
    }
