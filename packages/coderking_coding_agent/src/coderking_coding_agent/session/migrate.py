"""Legacy session.json → JSONL migration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from coderking_coding_agent.session.repo import SessionRepo


def legacy_session_path(workspace: Path) -> Path:
    return workspace.resolve() / ".coderking" / "session.json"


def import_legacy_session(
    workspace: Path,
    *,
    session_id: str = "default",
    legacy_path: Path | None = None,
) -> SessionRepo | None:
    """Import flat session.json into a new SessionRepo; return None if no legacy file."""
    path = legacy_path or legacy_session_path(workspace)
    if not path.is_file():
        return None
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    repo = SessionRepo(workspace, session_id=session_id)
    if raw:
        repo.append("message", {"session_snapshot": raw})
    for msg in raw.get("messages") or []:
        if isinstance(msg, dict):
            repo.append("message", {"message": msg})
    return repo
