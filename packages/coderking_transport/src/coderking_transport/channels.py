"""L3 transport channel contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol


class TransportKind(StrEnum):
    CLI = "cli"
    HTTP = "http"
    SSE = "sse"
    RPC_STDIO = "rpc_stdio"
    DESKTOP = "desktop"


class EventPublisher(Protocol):
    async def publish(self, event: dict[str, Any]) -> None: ...


class ControlChannel(Protocol):
    async def prompt(self, text: str) -> None: ...

    async def steer(self, text: str) -> None: ...

    async def follow_up(self, text: str) -> None: ...

    async def abort(self) -> None: ...
