"""Append-only JSONL session repository with tree branching."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from coderking_coding_agent.session.models import (
    SessionNode,
    SessionNodeKind,
    new_node_id,
    utc_now_iso,
)


class SessionRepo:
    """Pi-style append-only session store: one JSON object per line, head pointer file."""

    def __init__(self, workspace: Path, *, session_id: str = "default") -> None:
        self.workspace = workspace.resolve()
        self.session_id = session_id
        self._dir = self.workspace / ".coderking" / "sessions"
        self._dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self._dir / f"{session_id}.jsonl"
        self.head_path = self._dir / f"{session_id}.head"
        self._nodes: dict[str, SessionNode] = {}
        self._head_id: str | None = None
        self._load()

    @property
    def head_id(self) -> str | None:
        return self._head_id

    def append(
        self,
        kind: SessionNodeKind,
        payload: dict[str, Any],
        *,
        parent_id: str | None = None,
        node_id: str | None = None,
    ) -> SessionNode:
        parent = parent_id if parent_id is not None else self._head_id
        if parent is not None and parent not in self._nodes:
            raise KeyError(f"unknown parent_id: {parent}")
        node = SessionNode(
            id=node_id or new_node_id(),
            parent_id=parent,
            kind=kind,
            payload=payload,
            created_at=utc_now_iso(),
        )
        self._write_line(node)
        self._nodes[node.id] = node
        self._head_id = node.id
        self._save_head()
        return node

    def branch_to(self, node_id: str) -> None:
        if node_id not in self._nodes:
            raise KeyError(f"unknown node_id: {node_id}")
        self._head_id = node_id
        self._save_head()

    def walk_to_head(self) -> list[SessionNode]:
        if self._head_id is None:
            return []
        chain: list[SessionNode] = []
        current: str | None = self._head_id
        seen: set[str] = set()
        while current is not None:
            if current in seen:
                raise ValueError(f"cycle detected at node {current}")
            seen.add(current)
            node = self._nodes.get(current)
            if node is None:
                raise ValueError(f"missing node on head chain: {current}")
            chain.append(node)
            current = node.parent_id
        chain.reverse()
        return chain

    def materialize_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for node in self.walk_to_head():
            if node.kind == "message":
                msg = node.payload.get("message")
                if isinstance(msg, dict):
                    messages.append(msg)
            elif node.kind == "compression":
                summary = node.payload.get("summary")
                if isinstance(summary, dict):
                    messages.append(summary)
        return messages

    def materialize_session_state(self) -> dict[str, Any]:
        """Return latest full session snapshot from the head chain."""
        for node in reversed(self.walk_to_head()):
            snapshot = node.payload.get("session_snapshot")
            if isinstance(snapshot, dict):
                return dict(snapshot)
        return {}

    def recover_tail(self) -> int:
        """Truncate corrupt trailing bytes; return number of bytes removed."""
        if not self.jsonl_path.is_file():
            return 0
        raw = self.jsonl_path.read_bytes()
        if not raw:
            return 0
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        valid_end = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                valid_end = sum(len(lines[j]) for j in range(i + 1))
                continue
            try:
                json.loads(stripped)
                valid_end = sum(len(lines[j]) for j in range(i + 1))
            except json.JSONDecodeError:
                break
        removed = len(raw) - valid_end
        if removed > 0:
            self.jsonl_path.write_bytes(raw[:valid_end])
        return removed

    def _load(self) -> None:
        if self.jsonl_path.is_file():
            self.recover_tail()
        self._load_lines()
        self._load_head()
        if not self._nodes:
            root = SessionNode(
                id=new_node_id(),
                parent_id=None,
                kind="system",
                payload={"label": "root"},
                created_at=utc_now_iso(),
            )
            self._write_line(root)
            self._nodes[root.id] = root
            self._head_id = root.id
            self._save_head()

    def _load_lines(self) -> None:
        self._nodes.clear()
        if not self.jsonl_path.is_file():
            return
        text = self.jsonl_path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
                node = SessionNode.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError(f"invalid jsonl line {line_no}: {exc}") from exc
            self._nodes[node.id] = node

    def _load_head(self) -> None:
        self._head_id = None
        if not self.head_path.is_file():
            if self._nodes:
                roots = [n for n in self._nodes.values() if n.parent_id is None]
                if roots:
                    self._head_id = roots[-1].id
            return
        try:
            data = json.loads(self.head_path.read_text(encoding="utf-8"))
            head = data.get("head_id")
            if isinstance(head, str) and head in self._nodes:
                self._head_id = head
        except json.JSONDecodeError:
            pass

    def _write_line(self, node: SessionNode) -> None:
        line = node.to_json_line() + "\n"
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def _save_head(self) -> None:
        payload = json.dumps({"head_id": self._head_id}, ensure_ascii=False)
        self.head_path.write_text(payload, encoding="utf-8")
