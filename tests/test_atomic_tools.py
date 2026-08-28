from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from coderking.config import Settings
from coderking.tools.registry import (
    ATOMIC_TOOL_NAMES,
    build_atomic_tools,
    build_swe_tools,
    build_tools,
)
from coderking_coding_agent.extensions_swe import SWE_EXTENSION, default_registry, register_swe


def test_atomic_tools_are_four_pi_names() -> None:
    workspace = Path(".")
    sandbox = MagicMock()
    settings = Settings(extension="atomic")
    tools = build_atomic_tools(workspace, sandbox, settings)
    assert set(tools) == ATOMIC_TOOL_NAMES
    assert len(tools) == 4


def test_swe_tools_include_harness_meta_tools() -> None:
    workspace = Path(".")
    sandbox = MagicMock()
    settings = Settings(extension="swe")
    tools = build_swe_tools(workspace, sandbox, settings)
    assert "read_file" in tools
    assert "submit_plan" in tools
    assert "run_tests" in tools
    assert len(tools) > 4


def test_build_tools_respects_extension_setting() -> None:
    workspace = Path(".")
    sandbox = MagicMock()
    atomic = build_tools(workspace, sandbox, Settings(extension="atomic"))
    swe = build_tools(workspace, sandbox, Settings(extension="swe"))
    assert set(atomic) == ATOMIC_TOOL_NAMES
    assert "finish_task" in swe


def test_swe_extension_registered() -> None:
    registry = default_registry()
    assert "swe" in registry.names()
    assert registry.get("swe").metadata["tool_profile"] == "swe"


def test_register_swe_idempotent_names() -> None:
    from coderking_coding_agent.extensions import ExtensionRegistry

    registry = ExtensionRegistry()
    register_swe(registry)
    assert registry.names() == ["swe"]
    assert SWE_EXTENSION.name == "swe"
