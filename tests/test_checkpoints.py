from __future__ import annotations

from pathlib import Path

import pytest

from coderking.runtime.checkpoints import CheckpointStore


def test_checkpoint_restores_overwritten_binary_file(tmp_path: Path) -> None:
    target = tmp_path / "asset.bin"
    target.write_bytes(b"\x00before\xff")
    store = CheckpointStore(tmp_path, tmp_path, "task-a")
    prepared = store.prepare(
        turn_id="turn_a",
        tool_call_id="call-a",
        tool="write",
        arguments={"path": "asset.bin"},
    )
    assert prepared is not None and prepared.recoverable
    target.write_bytes(b"after")

    applied = store.complete(prepared.checkpoint_id, ok=True)
    restored = store.restore(prepared.checkpoint_id)

    assert applied["status"] == "applied"
    assert restored["status"] == "rolled_back"
    assert target.read_bytes() == b"\x00before\xff"


def test_checkpoint_removes_file_created_by_tool(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path, tmp_path, "task-new")
    prepared = store.prepare(
        turn_id="turn_a",
        tool_call_id=None,
        tool="write",
        arguments={"path": "new.txt"},
    )
    assert prepared is not None
    (tmp_path / "new.txt").write_text("created", encoding="utf-8")
    store.complete(prepared.checkpoint_id, ok=True)

    store.restore(prepared.checkpoint_id)

    assert not (tmp_path / "new.txt").exists()


def test_accepted_checkpoint_cannot_be_rolled_back(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("before", encoding="utf-8")
    store = CheckpointStore(tmp_path, tmp_path, "task-accepted")
    prepared = store.prepare(
        turn_id=None,
        tool_call_id=None,
        tool="edit",
        arguments={"path": "a.txt"},
    )
    assert prepared is not None
    target.write_text("after", encoding="utf-8")
    store.complete(prepared.checkpoint_id, ok=True)

    assert store.accept_all() == 1
    with pytest.raises(ValueError, match="accepted checkpoint"):
        store.restore(prepared.checkpoint_id)


def test_checkpoint_marks_oversized_original_unrecoverable(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_text("1234", encoding="utf-8")
    store = CheckpointStore(tmp_path, tmp_path, "task-large", max_file_bytes=3)

    prepared = store.prepare(
        turn_id=None,
        tool_call_id=None,
        tool="write",
        arguments={"path": "large.txt"},
    )

    assert prepared is not None
    assert prepared.recoverable is False
    assert "exceeds checkpoint limit" in (prepared.reason or "")


def test_non_mutating_tool_does_not_create_checkpoint(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path, tmp_path, "task-read")

    prepared = store.prepare(
        turn_id=None,
        tool_call_id=None,
        tool="read",
        arguments={"path": "a.txt"},
    )

    assert prepared is None
    assert store.list() == []


def test_checkpoint_refuses_to_overwrite_content_changed_after_tool(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("before", encoding="utf-8")
    store = CheckpointStore(tmp_path, tmp_path, "task-diverged")
    prepared = store.prepare(
        turn_id="turn_a",
        tool_call_id="call_a",
        tool="edit",
        arguments={"path": "a.txt"},
    )
    assert prepared is not None
    target.write_text("tool result", encoding="utf-8")
    store.complete(prepared.checkpoint_id, ok=True)
    target.write_text("newer user edit", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after checkpoint"):
        store.restore(prepared.checkpoint_id)

    assert target.read_text(encoding="utf-8") == "newer user edit"


def test_checkpoint_restore_preserves_original_mode(tmp_path: Path) -> None:
    target = tmp_path / "script.sh"
    target.write_text("before", encoding="utf-8")
    target.chmod(0o755)
    store = CheckpointStore(tmp_path, tmp_path, "task-mode")
    prepared = store.prepare(
        turn_id=None,
        tool_call_id=None,
        tool="write",
        arguments={"path": "script.sh"},
    )
    assert prepared is not None
    target.write_text("after", encoding="utf-8")
    target.chmod(0o644)
    store.complete(prepared.checkpoint_id, ok=True)

    store.restore(prepared.checkpoint_id)

    assert target.stat().st_mode & 0o777 == 0o755


def test_full_rollback_marker_overrides_accepted_checkpoint(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("before", encoding="utf-8")
    store = CheckpointStore(tmp_path, tmp_path, "task-full-rollback")
    prepared = store.prepare(
        turn_id=None,
        tool_call_id=None,
        tool="edit",
        arguments={"path": "a.txt"},
    )
    assert prepared is not None
    target.write_text("after", encoding="utf-8")
    store.complete(prepared.checkpoint_id, ok=True)
    store.accept_all()

    assert store.mark_all_rolled_back() == 1
    assert store.load(prepared.checkpoint_id)["status"] == "rolled_back"


def test_checkpoint_size_limit_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        CheckpointStore(tmp_path, tmp_path, "task-limit", max_file_bytes=0)
