from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from coderking.tools.dynamic_adapter import DynamicTool, wrap_dynamic_tools
from coderking_coding_agent.tools.dynamic import (
    DynamicToolLoader,
    ToolValidationError,
    parse_tool_manifest,
    scan_tool_manifests,
)


class _FakeRunner:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def run(self, command: str, *, timeout_sec: int) -> tuple[int, str]:
        _ = timeout_sec
        self.commands.append(command)
        return 0, "ok"


def _write_tool(workspace: Path, name: str, *, entry: str = "main.py") -> None:
    tool_dir = workspace / ".coderking" / "tools" / name
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / entry).write_text(
        "import json, os\n"
        "args=json.loads(os.environ.get('CODERKING_TOOL_ARGS','{}'))\n"
        "print(args.get('msg',''))\n",
        encoding="utf-8",
    )
    manifest = {
        "name": name,
        "description": f"tool {name}",
        "entry": entry,
        "parameters": {
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
    }
    (tool_dir / "tool.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")


def test_parse_tool_manifest_valid(tmp_path: Path) -> None:
    _write_tool(tmp_path, "echo_tool")
    manifest = parse_tool_manifest(tmp_path / ".coderking" / "tools" / "echo_tool", tmp_path)
    assert manifest.name == "echo_tool"


def test_parse_tool_manifest_rejects_bad_entry(tmp_path: Path) -> None:
    _write_tool(tmp_path, "bad_tool")
    tool_dir = tmp_path / ".coderking" / "tools" / "bad_tool"
    data = yaml.safe_load((tool_dir / "tool.yaml").read_text(encoding="utf-8"))
    data["entry"] = "../secrets/main.py"
    (tool_dir / "tool.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ToolValidationError):
        parse_tool_manifest(tool_dir, tmp_path)


def test_parse_tool_manifest_rejects_name_mismatch(tmp_path: Path) -> None:
    _write_tool(tmp_path, "good")
    tool_dir = tmp_path / ".coderking" / "tools" / "good"
    data = yaml.safe_load((tool_dir / "tool.yaml").read_text(encoding="utf-8"))
    data["name"] = "other"
    (tool_dir / "tool.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ToolValidationError):
        parse_tool_manifest(tool_dir, tmp_path)


def test_scan_collects_validation_errors(tmp_path: Path) -> None:
    _write_tool(tmp_path, "valid_tool")
    bad = tmp_path / ".coderking" / "tools" / "bad"
    bad.mkdir(parents=True)
    (bad / "tool.yaml").write_text("not: [a, mapping, ok]", encoding="utf-8")
    manifests, errors = scan_tool_manifests(tmp_path)
    assert len(manifests) == 1
    assert "bad" in errors


@pytest.mark.asyncio
async def test_dynamic_tool_executes_via_sandbox_runner(tmp_path: Path) -> None:
    _write_tool(tmp_path, "echo_tool")
    runner = _FakeRunner()
    loader = DynamicToolLoader(tmp_path, runner, timeout_sec=5)
    tools = wrap_dynamic_tools(loader.refresh())
    tool = tools["echo_tool"]
    assert isinstance(tool, DynamicTool)
    assert tool.requires_approval is True
    result = await tool.execute(msg="hello")
    assert result.ok
    assert runner.commands
    assert "main.py" in runner.commands[0]
    assert "CODERKING_TOOL_ARGS" in runner.commands[0]


def test_loader_discovers_tool_on_second_refresh(tmp_path: Path) -> None:
    runner = _FakeRunner()
    loader = DynamicToolLoader(tmp_path, runner)
    assert loader.refresh() == {}
    _write_tool(tmp_path, "late_tool")
    loaded = loader.refresh()
    assert "late_tool" in loaded
    assert loader.names() == frozenset({"late_tool"})
