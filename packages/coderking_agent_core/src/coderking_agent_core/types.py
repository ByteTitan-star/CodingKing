"""L1 loop contracts — implementation lands in #24."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class LoopPhase(StrEnum):
    PERCEIVE = "perceive"
    DECIDE = "decide"
    ACT = "act"
    OBSERVE = "observe"
    RE_PERCEIVE = "re_perceive"
    TERMINATED = "terminated"


@dataclass
class AgentMessage:
    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[..., Awaitable[Any]]


@dataclass
class AgentContext:
    system_prompt: str
    messages: list[AgentMessage] = field(default_factory=list)
    tools: list[AgentTool] = field(default_factory=list)


class AgentEventSink(Protocol):
    async def __call__(self, event: dict[str, Any]) -> None: ...


TransformContext = Callable[[Sequence[AgentMessage]], Awaitable[list[AgentMessage]]]
