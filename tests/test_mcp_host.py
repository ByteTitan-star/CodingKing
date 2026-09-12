"""MCP host integration tests (mock stdio server)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.llm.provider import LLMResponse, ToolCall
from coderking.mcp.config import load_mcp_config
from coderking.mcp.host import McpHost
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import TaskStatus
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


def test_empty_allowlist_starts_no_servers(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".coderking"
    cfg_dir.mkdir()
    (cfg_dir / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "evil": {"command": "python", "args": ["-c", "pass"], "enabled": True},
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_mcp_config(tmp_path)
    assert cfg.selected() == []


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


@pytest.mark.asyncio
async def test_runtime_exposes_allowlisted_mcp_tool_when_enabled(tmp_path: Path) -> None:
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
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class _LLM:
        def __init__(self) -> None:
            self.turn = 0
            self.tools: list[dict] = []

        async def complete(self, messages, tools, cancel=None):  # noqa: ANN001, ARG002
            self.tools = list(tools)
            self.turn += 1
            if self.turn == 1:
                return LLMResponse(
                    "",
                    [
                        ToolCall(
                            id="mcp-1",
                            name="mcp_demo_echo",
                            arguments={"message": "hello"},
                        )
                    ],
                )
            return LLMResponse("done", [])

    llm = _LLM()
    settings = Settings(
        openai_api_key="x",
        workspace=tmp_path,
        sandbox_mode="local",
        mcp_enabled=True,
        mcp_timeout_sec=30,
    )
    state = await AgentRuntime(settings, llm).run(
        "use MCP",
        tmp_path,
        on_event=lambda _event: _async_none(),
        auto_approve=True,
    )

    names = {(tool.get("function") or {}).get("name") for tool in llm.tools}
    assert "mcp_demo_echo" in names
    assert state.status == TaskStatus.SUCCEEDED
    assert any(
        record.name == "mcp_demo_echo" and "echo:hello" in record.output
        for record in state.tool_history
    )


async def _async_none() -> None:
    return None
