"""Incremental scrollback buffer for TUI panels."""

from __future__ import annotations

DEFAULT_MAX_LINES = 10_000


class ScrollbackLog:
    """Append-only line buffer with bounded retention."""

    def __init__(self, *, max_lines: int = DEFAULT_MAX_LINES) -> None:
        self.max_lines = max_lines
        self._lines: list[str] = []

    def append(self, line: str) -> None:
        if not line:
            return
        self._lines.append(line)
        overflow = len(self._lines) - self.max_lines
        if overflow > 0:
            self._lines = self._lines[overflow:]

    def extend(self, lines: list[str]) -> None:
        for line in lines:
            self.append(line)

    def lines(self) -> list[str]:
        return list(self._lines)

    def tail(self, count: int) -> list[str]:
        if count <= 0:
            return []
        return self._lines[-count:]

    def __len__(self) -> int:
        return len(self._lines)
