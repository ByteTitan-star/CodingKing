"""Stateful Agent wrapper with steering / follow-up queues."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from coderking_agent_core.cancel import CancelledRun, RunCancel
from coderking_agent_core.loop import (
    AgentLoopConfig,
    CompleteTurnFn,
    ShouldStopFn,
    TransformContextFn,
    run_agent_loop,
)
from coderking_agent_core.types import AgentContext, AgentMessage, AgentTool

QueueMode = Literal["one-at-a-time", "all"]


@dataclass
class _MessageQueue:
    mode: QueueMode = "one-at-a-time"
    _items: list[AgentMessage] = field(default_factory=list)

    def enqueue(self, message: AgentMessage) -> None:
        self._items.append(message)

    def drain(self) -> list[AgentMessage]:
        if not self._items:
            return []
        if self.mode == "all":
            drained = self._items[:]
            self._items.clear()
            return drained
        first = self._items.pop(0)
        return [first]

    def clear(self) -> None:
        self._items.clear()


class Agent:
    """Pi-style stateful agent: prompt, steer, follow_up, abort, subscribe."""

    def __init__(
        self,
        *,
        system_prompt: str = "",
        tools: list[AgentTool] | None = None,
        complete_turn: CompleteTurnFn,
        transform_context: TransformContextFn | None = None,
        should_stop_after_turn: ShouldStopFn | None = None,
        max_turns: int = 24,
        tool_execution: Literal["sequential", "parallel"] = "parallel",
        steering_mode: QueueMode = "one-at-a-time",
        follow_up_mode: QueueMode = "one-at-a-time",
    ) -> None:
        if complete_turn is None:
            raise ValueError("complete_turn is required")
        self._context = AgentContext(
            system_prompt=system_prompt,
            tools=list(tools or []),
        )
        self._complete_turn = complete_turn
        self._transform_context = transform_context
        self._should_stop_after_turn = should_stop_after_turn
        self._max_turns = max_turns
        self._tool_execution = tool_execution
        self._steering = _MessageQueue(mode=steering_mode)
        self._follow_up = _MessageQueue(mode=follow_up_mode)
        self._cancel = RunCancel()
        self._listeners: list[Callable[[dict[str, Any]], Awaitable[None]]] = []
        self._run_task: asyncio.Task[AgentContext] | None = None

    @property
    def context(self) -> AgentContext:
        return self._context

    def subscribe(
        self, listener: Callable[[dict[str, Any]], Awaitable[None]]
    ) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def steer(self, message: AgentMessage) -> None:
        self._steering.enqueue(message)

    def follow_up(self, message: AgentMessage) -> None:
        self._follow_up.enqueue(message)

    def abort(self) -> None:
        self._cancel.abort()
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()

    async def prompt(self, message: AgentMessage | str) -> AgentContext:
        if self._run_task and not self._run_task.done():
            raise RuntimeError("Agent is busy; use steer() or follow_up()")
        user = (
            message
            if isinstance(message, AgentMessage)
            else AgentMessage(role="user", content=message)
        )
        self._run_task = asyncio.create_task(self._run([user]))
        try:
            return await self._run_task
        finally:
            self._run_task = None

    async def _drain_steering(self) -> list[AgentMessage]:
        return self._steering.drain()

    async def _drain_follow_up(self) -> list[AgentMessage]:
        return self._follow_up.drain()

    async def _run(self, initial: list[AgentMessage]) -> AgentContext:
        async def emit(event: dict[str, Any]) -> None:
            for listener in list(self._listeners):
                await listener(event)

        config = AgentLoopConfig(
            complete_turn=self._complete_turn,
            transform_context=self._transform_context,
            get_steering_messages=self._drain_steering,
            get_follow_up_messages=self._drain_follow_up,
            should_stop_after_turn=self._should_stop_after_turn,
            max_turns=self._max_turns,
            tool_execution=self._tool_execution,
            cancel=self._cancel,
        )
        try:
            self._context = await run_agent_loop(
                self._context,
                config,
                emit,
                initial_messages=initial,
            )
            return self._context
        except CancelledRun:
            await emit({"type": "agent_end", "ok": False, "reason": "aborted"})
            return self._context
        except asyncio.CancelledError:
            await emit({"type": "agent_end", "ok": False, "reason": "aborted"})
            raise
