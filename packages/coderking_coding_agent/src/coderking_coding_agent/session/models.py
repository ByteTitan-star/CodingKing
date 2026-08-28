"""Session node model for append-only JSONL trees."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

SessionNodeKind = Literal["message", "compression", "branch_marker", "system"]


def new_node_id() -> str:
    return uuid4().hex


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass
class SessionNode:
    id: str
    parent_id: str | None
    kind: SessionNodeKind
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionNode:
        return cls(
            id=str(data["id"]),
            parent_id=data.get("parent_id"),
            kind=data["kind"],
            payload=dict(data.get("payload") or {}),
            created_at=str(data.get("created_at") or utc_now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json_line(self) -> str:
        import json

        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
