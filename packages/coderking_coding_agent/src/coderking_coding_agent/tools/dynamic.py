"""Dynamic user-defined tools under .coderking/tools/{name}/."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

SAFE_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ALLOWED_ENTRIES = frozenset({"main.py", "main.sh"})


class ToolValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DynamicToolManifest:
    name: str
    description: str
    parameters: dict[str, Any]
    entry: Path
    tool_dir: Path


class SandboxRunner(Protocol):
    async def run(self, command: str, *, timeout_sec: int) -> tuple[int, str]: ...


def tools_root(workspace: Path) -> Path:
    return workspace.resolve() / ".coderking" / "tools"


def parse_tool_manifest(tool_dir: Path, workspace: Path) -> DynamicToolManifest:
    """Parse and validate `.coderking/tools/{name}/tool.yaml`."""
    root = workspace.resolve()
    directory = tool_dir.resolve()
    if not directory.is_dir():
        raise ToolValidationError(f"not a directory: {directory}")
    try:
        directory.relative_to(tools_root(root))
    except ValueError as exc:
        raise ToolValidationError("tool dir must live under .coderking/tools") from exc

    manifest_path = directory / "tool.yaml"
    if not manifest_path.is_file():
        raise ToolValidationError("missing tool.yaml")

    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ToolValidationError("tool.yaml must be a mapping")

    name = str(raw.get("name") or "").strip()
    if name != directory.name:
        raise ToolValidationError("tool name must match directory name")
    if not SAFE_TOOL_NAME.fullmatch(name):
        raise ToolValidationError("invalid tool name")

    description = str(raw.get("description") or "").strip()
    if not description:
        raise ToolValidationError("description is required")

    parameters = raw.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("type") != "object":
        raise ToolValidationError("parameters must be a JSON schema object")

    entry_name = str(raw.get("entry") or "main.py").replace("\\", "/").lstrip("./")
    if entry_name != Path(entry_name).name:
        raise ToolValidationError("entry must be a basename under the tool directory")
    if entry_name not in ALLOWED_ENTRIES:
        raise ToolValidationError("entry must be main.py or main.sh")

    entry = (directory / entry_name).resolve()
    try:
        entry.relative_to(directory)
    except ValueError as exc:
        raise ToolValidationError("entry escapes tool directory") from exc
    if not entry.is_file():
        raise ToolValidationError(f"missing entry script: {entry_name}")

    return DynamicToolManifest(
        name=name,
        description=description,
        parameters=parameters,
        entry=entry,
        tool_dir=directory,
    )


def scan_tool_manifests(workspace: Path) -> tuple[list[DynamicToolManifest], dict[str, str]]:
    root = tools_root(workspace)
    manifests: list[DynamicToolManifest] = []
    errors: dict[str, str] = {}
    if not root.is_dir():
        return manifests, errors
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        try:
            manifests.append(parse_tool_manifest(child, workspace))
        except ToolValidationError as exc:
            errors[child.name] = str(exc)
    return manifests, errors


@dataclass
class DynamicToolExecutor:
    manifest: DynamicToolManifest
    workspace: Path
    runner: SandboxRunner
    timeout_sec: int

    requires_approval: bool = True

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def description(self) -> str:
        return self.manifest.description

    @property
    def parameters(self) -> dict[str, Any]:
        return self.manifest.parameters

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def execute(self, **kwargs: Any) -> tuple[bool, str]:
        rel_entry = self.manifest.entry.relative_to(self.workspace.resolve()).as_posix()
        payload = json.dumps(kwargs, ensure_ascii=False)
        quoted = shlex.quote(payload)
        if self.manifest.entry.suffix == ".py":
            command = f"CODERKING_TOOL_ARGS={quoted} python {shlex.quote(rel_entry)}"
        else:
            command = f"CODERKING_TOOL_ARGS={quoted} bash {shlex.quote(rel_entry)}"
        code, output = await self.runner.run(command, timeout_sec=self.timeout_sec)
        return code == 0, output


class DynamicToolLoader:
    """Session-scoped dynamic tool registry (rescanned each refresh)."""

    def __init__(
        self,
        workspace: Path,
        runner: SandboxRunner,
        *,
        timeout_sec: int = 120,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runner = runner
        self.timeout_sec = timeout_sec
        self._executors: dict[str, DynamicToolExecutor] = {}
        self.errors: dict[str, str] = {}

    def refresh(self) -> dict[str, DynamicToolExecutor]:
        manifests, errors = scan_tool_manifests(self.workspace)
        self.errors = errors
        loaded: dict[str, DynamicToolExecutor] = {}
        for manifest in manifests:
            loaded[manifest.name] = DynamicToolExecutor(
                manifest,
                self.workspace,
                self.runner,
                timeout_sec=self.timeout_sec,
            )
        self._executors = loaded
        return loaded

    def names(self) -> frozenset[str]:
        return frozenset(self._executors)

    def get(self, name: str) -> DynamicToolExecutor | None:
        return self._executors.get(name)

    def all(self) -> dict[str, DynamicToolExecutor]:
        return dict(self._executors)


RunHook = Callable[[DynamicToolExecutor], Awaitable[None] | None]


async def before_tool_call(
    executor: DynamicToolExecutor, *, on_load: RunHook | None = None
) -> None:
    if on_load is not None:
        maybe = on_load(executor)
        if maybe is not None:
            await maybe
