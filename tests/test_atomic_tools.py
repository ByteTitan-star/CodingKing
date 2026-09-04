"""Atomic coding tools only."""

from __future__ import annotations

from pathlib import Path

from coderking.config import Settings
from coderking.sandbox.local import LocalProcessSandbox
from coderking.tools.registry import ATOMIC_TOOL_NAMES, build_atomic_tools, build_tools
from coderking_coding_agent.extensions import ExtensionRegistry


def test_atomic_tools_are_four() -> None:
    workspace = Path(".")
    sandbox = LocalProcessSandbox(workspace)
    settings = Settings()
    tools = build_atomic_tools(workspace, sandbox, settings)
    assert set(tools) == ATOMIC_TOOL_NAMES
    assert "submit_plan" not in tools
    assert "run_tests" not in tools


def test_build_tools_is_always_atomic() -> None:
    workspace = Path(".")
    sandbox = LocalProcessSandbox(workspace)
    tools = build_tools(workspace, sandbox, Settings())
    assert set(tools) == ATOMIC_TOOL_NAMES


def test_extension_registry_starts_empty() -> None:
    registry = ExtensionRegistry()
    assert registry.names() == []
