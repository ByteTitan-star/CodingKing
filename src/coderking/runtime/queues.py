"""Steering and follow-up message queues for in-run control."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class RunMessageQueues:
    """Thread-safe queues for steer (redirect) vs follow-up (after stop)."""

    steering: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    follow_up: asyncio.Queue[str] = field(default_factory=asyncio.Queue)

    def enqueue_steer(self, content: str) -> None:
        text = content.strip()
        if text:
            self.steering.put_nowait(text)

    def enqueue_follow_up(self, content: str) -> None:
        text = content.strip()
        if text:
            self.follow_up.put_nowait(text)

    async def drain_steering(self) -> list[str]:
        return await _drain_queue(self.steering)

    async def drain_follow_up(self) -> list[str]:
        return await _drain_queue(self.follow_up)


async def _drain_queue(queue: asyncio.Queue[str]) -> list[str]:
    items: list[str] = []
    while True:
        try:
            items.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return items
