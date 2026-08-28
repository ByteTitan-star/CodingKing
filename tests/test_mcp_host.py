"""MCP host integration tests (mock stdio server)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from coderking.mcp.config import load_mcp_config
from coderking.mcp.host import McpHost
from coderking_coding_agent.safety.policy import PolicyAction, PolicyEngine


def test_load_mcp_config_allowlist(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".coderking"
    cfg_dir.mkdir()
    (cfg_dir / "mcp.json").write_text(
        json.dumps(
            {
                "allowlist": ["demo"],
                "mcpServers": {
                    "demo": {"command": "python", "args": ["-c", "pass"], "enabled": True},
                    "other": {"command": "python", "args": ["-c", "pass"], "enabled": True},
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_mcp_config(tmp_path)
    names = [s.name for s in cfg.selected()]
    assert names == ["demo"]


def test_policy_mcp_tools_default_ask() -> None:
    engine = PolicyEngine({"tools": {"mcp_*": {"default_action": "ask"}}})
    decision = engine.evaluate("mcp_demo_echo", {"message": "hi"})
    assert decision.action == PolicyAction.ASK


@pytest.mark.asyncio
async def test_mcp_host_mock_echo(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".coderking"
    cfg_dir.mkdir()
    (cfg_dir / "mcp.json").write_text(
        json.dumps(
            {
                "allowlist": ["demo"],
                "mcpServers": {
                    "demo": {
                        "command": sys.executable,
                        "args": ["-m", "coderking.mcp.mock_server"],
                        "enabled": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    host = await McpHost.connect(tmp_path, timeout_sec=30)
    try:
        assert "mcp_demo_echo" in host.names()
        tool = host.tools()["mcp_demo_echo"]
        result = await tool.execute(message="hello")
        assert result.ok
        assert "echo:hello" in result.output
    finally:
        await host.close()
