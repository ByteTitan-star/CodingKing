"""String-replace edit tool (Pi-style uniqueness + fuzzy whitespace)."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path
from typing import Any

from coderking.tools.base import ToolResult
from coderking.tools.file import FileTool, invalidate_bytecode

_OBJ = {"type": "object"}


@dataclass(frozen=True)
class EditMatchInfo:
    match_count: int
    used_fuzzy: bool = False


def apply_string_replace(
    text: str,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
) -> tuple[str, EditMatchInfo]:
    if old_string == "":
        raise ValueError("old_string must not be empty")
    if old_string == new_string:
        raise ValueError("old_string and new_string are identical")

    count = text.count(old_string)
    if count == 0:
        fuzzy_old, fuzzy_text = _normalize_for_fuzzy(old_string), _normalize_for_fuzzy(text)
        if fuzzy_old != old_string or fuzzy_text != text:
            count = fuzzy_text.count(fuzzy_old)
            if count == 1:
                text = _apply_fuzzy_replace(text, old_string, new_string)
                return text, EditMatchInfo(match_count=1, used_fuzzy=True)
        raise ValueError("old_string matched 0 occurrences; provide more surrounding context")

    if count > 1 and not replace_all:
        raise ValueError(
            f"old_string matched {count} occurrences; must be unique or set replace_all=true"
        )

    if replace_all:
        return text.replace(old_string, new_string), EditMatchInfo(match_count=count)

    return text.replace(old_string, new_string, 1), EditMatchInfo(match_count=1)


def _normalize_for_fuzzy(text: str) -> str:
    """Normalize EOL and expand tabs for tolerant matching."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.expandtabs(4)
    return normalized


def _apply_fuzzy_replace(text: str, old_string: str, new_string: str) -> str:
    """Apply edit when fuzzy-normalized forms match uniquely."""
    norm_text = _normalize_for_fuzzy(text)
    norm_old = _normalize_for_fuzzy(old_string)
    idx = norm_text.find(norm_old)
    if idx < 0:
        raise ValueError("fuzzy match failed")
    # Map normalized index back to original span by line-wise alignment.
    orig_lines = text.splitlines(keepends=True)
    norm_lines = norm_text.splitlines(keepends=True)
    if len(orig_lines) != len(norm_lines):
        # Fallback: replace on normalized copy preserving original EOL style
        eol = "\r\n" if "\r\n" in text else "\n"
        rebuilt = norm_text.replace(norm_old, _normalize_for_fuzzy(new_string))
        if eol != "\n":
            rebuilt = rebuilt.replace("\n", eol)
        return rebuilt
    # Line-block replace when old_string spans whole lines
    old_lines = old_string.splitlines()
    if not old_lines:
        raise ValueError("old_string must not be empty")
    window = len(old_lines)
    norm_old_stripped = norm_old.rstrip("\n\r")
    for i in range(len(orig_lines) - window + 1):
        block = "".join(orig_lines[i : i + window])
        if _normalize_for_fuzzy(block).rstrip("\n\r") == norm_old_stripped:
            new_block = new_string
            if not new_string.endswith("\n") and block.endswith("\n"):
                new_block = new_string + ("\n" if not new_string.endswith("\r\n") else "")
            return "".join(orig_lines[:i]) + new_block + "".join(orig_lines[i + window :])
    raise ValueError("fuzzy match failed")


def _short_diff(before: str, after: str, rel: str) -> str:
    lines = unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
        n=2,
    )
    snippet = "".join(lines)
    if len(snippet) > 2000:
        return snippet[:2000] + "\n...[diff truncated]"
    return snippet or "(no diff)"


class EditFileTool(FileTool):
    def __init__(self, workspace: Path, *, name: str = "edit_file"):
        super().__init__(
            workspace,
            name=name,
            description=(
                "Replace old_string with new_string in a UTF-8 text file. "
                "old_string must match exactly once unless replace_all is true."
            ),
            parameters={
                **_OBJ,
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        rel = str(kwargs["path"]).replace("\\", "/")
        path = self._resolve(rel)
        if not path.is_file():
            return ToolResult(False, f"not found: {rel}")
        old_string = str(kwargs["old_string"])
        new_string = str(kwargs["new_string"])
        replace_all = bool(kwargs.get("replace_all", False))
        try:
            before = path.read_text(encoding="utf-8", errors="replace")
            if "\x00" in before:
                return ToolResult(False, f"binary file not supported: {rel}")
            after, info = apply_string_replace(
                before, old_string, new_string, replace_all=replace_all
            )
        except ValueError as exc:
            return ToolResult(False, str(exc))
        path.write_text(after, encoding="utf-8")
        invalidate_bytecode(path)
        diff = _short_diff(before, after, rel)
        fuzzy = " (fuzzy)" if info.used_fuzzy else ""
        return ToolResult(
            True,
            f"edited {rel}{fuzzy}\n{diff}",
            changed_file=rel,
            action="modified",
        )
