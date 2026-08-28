"""Load AGENTS.md / SYSTEM.md project instructions with mtime cache."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SEARCH_ORDER = ("AGENTS.md", "SYSTEM.md", ".coderking/AGENTS.md")
MAX_BYTES = 8192


@dataclass(frozen=True)
class ProjectInstructions:
    source: str
    content: str
    truncated: bool
    content_hash: str


def estimate_instruction_bytes(content: str) -> int:
    return len(content.encode("utf-8"))


def format_instruction_message(doc: ProjectInstructions) -> dict[str, Any]:
    body = doc.content.strip()
    text = f'<project_instructions source="{doc.source}">\n{body}\n</project_instructions>'
    return {
        "role": "user",
        "content": text,
        "meta": {
            "project_instructions": doc.source,
            "hash": doc.content_hash,
            "truncated": doc.truncated,
        },
    }


def has_project_instructions(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        content = str(message.get("content") or "")
        if "<project_instructions" in content:
            return True
    return False


class ProjectInstructionsLoader:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self._cache_key: str | None = None
        self._cached: ProjectInstructions | None = None

    def load(self) -> ProjectInstructions | None:
        for rel in SEARCH_ORDER:
            path = self.workspace / rel
            if path.is_file():
                return self._read(path, rel)
        self._cache_key = None
        self._cached = None
        return None

    def inspect(self) -> dict[str, Any]:
        doc = self.load()
        if doc is None:
            return {"loaded": False, "source": None, "hash": None, "truncated": False}
        return {
            "loaded": True,
            "source": doc.source,
            "hash": doc.content_hash,
            "truncated": doc.truncated,
            "bytes": estimate_instruction_bytes(doc.content),
        }

    def _read(self, path: Path, source: str) -> ProjectInstructions:
        stat = path.stat()
        cache_key = f"{path}:{stat.st_mtime_ns}:{stat.st_size}"
        if self._cache_key == cache_key and self._cached is not None:
            return self._cached

        raw = path.read_bytes()
        truncated = len(raw) > MAX_BYTES
        if truncated:
            raw = raw[:MAX_BYTES]
        content = raw.decode("utf-8", errors="replace")
        content_hash = hashlib.sha256(raw).hexdigest()[:16]
        doc = ProjectInstructions(
            source=source,
            content=content,
            truncated=truncated,
            content_hash=content_hash,
        )
        self._cache_key = cache_key
        self._cached = doc
        return doc


def inject_project_instructions(
    workspace: Path,
    messages: list[dict[str, Any]],
    *,
    loader: ProjectInstructionsLoader | None = None,
) -> tuple[list[dict[str, Any]], ProjectInstructions | None]:
    if has_project_instructions(messages):
        return messages, None
    active = loader or ProjectInstructionsLoader(workspace)
    doc = active.load()
    if doc is None:
        return messages, None
    instruction = format_instruction_message(doc)
    if messages and messages[0].get("role") == "system":
        return [messages[0], instruction, *messages[1:]], doc
    return [instruction, *messages], doc
