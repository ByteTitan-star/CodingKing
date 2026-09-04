"""L2 extension registry for optional capability packs (MCP, skills adapters)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Extension:
    name: str
    description: str
    register: Callable[[Any], None]
    metadata: dict[str, Any] = field(default_factory=dict)


class ExtensionRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Extension] = {}

    def add(self, extension: Extension) -> None:
        if extension.name in self._items:
            raise ValueError(f"extension already registered: {extension.name}")
        self._items[extension.name] = extension

    def get(self, name: str) -> Extension:
        return self._items[name]

    def names(self) -> list[str]:
        return sorted(self._items)
