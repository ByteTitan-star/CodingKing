"""Map agent event records to Server-Sent Events frames."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol


class TaskEventSource(Protocol):
    def get(self, task_id: str) -> Any: ...

    def subscribe_records(self, task_id: str) -> AsyncIterator[dict[str, Any]]: ...


def events_since(
    records: list[dict[str, Any]],
    last_event_id: str | None,
) -> list[dict[str, Any]]:
    if not records:
        return []
    if not last_event_id:
        return list(records)
    for index, record in enumerate(records):
        if record.get("id") == last_event_id:
            return records[index + 1 :]
    return list(records)


def format_sse_event(record: dict[str, Any]) -> str:
    event_id = str(record.get("id") or "")
    event_type = str(record.get("type") or "message")
    payload = record.get("payload", {})
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    for line in data.splitlines() or [""]:
        lines.append(f"data: {line}")
    lines.append("")
    return "\n".join(lines) + "\n"


async def stream_task_events(
    controller: TaskEventSource,
    task_id: str,
    *,
    last_event_id: str | None = None,
) -> AsyncIterator[str]:
    task = controller.get(task_id)
    snapshot = getattr(task, "snapshot", [])
    for record in events_since(snapshot, last_event_id):
        yield format_sse_event(record)
    async for record in controller.subscribe_records(task_id):
        yield format_sse_event(record)
