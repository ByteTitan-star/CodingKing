from pathlib import Path

import pytest

from coderking.diffing import restore_snapshot, snapshot_workspace, unified_diff


def test_unified_diff_and_rollback(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("old\n", encoding="utf-8")
    snap = snapshot_workspace(tmp_path)
    (tmp_path / "a.py").write_text("new\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("added\n", encoding="utf-8")
    diff = unified_diff(tmp_path, snap)
    assert "-old" in diff or "-old\n" in diff.replace("\r", "")
    assert "+new" in diff
    assert "b.py" in diff
    restore_snapshot(tmp_path, snap)
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "old\n"
    assert not (tmp_path / "b.py").exists()


def test_binary_snapshot_roundtrip_is_lossless(tmp_path: Path) -> None:
    original = b"\x00\xff\x01binary"
    (tmp_path / "asset.bin").write_bytes(original)
    snap = snapshot_workspace(tmp_path)
    (tmp_path / "asset.bin").write_bytes(b"changed")
    assert "Binary files" in unified_diff(tmp_path, snap)

    restore_snapshot(tmp_path, snap)

    assert (tmp_path / "asset.bin").read_bytes() == original


def test_incomplete_snapshot_refuses_destructive_rollback(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    snap = snapshot_workspace(tmp_path, max_files=1)
    (tmp_path / "new.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError, match="incomplete snapshot"):
        restore_snapshot(tmp_path, snap)

    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "keep me"


def test_empty_snapshot_refuses_rollback(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("safe", encoding="utf-8")
    with pytest.raises(ValueError, match="without a captured"):
        restore_snapshot(tmp_path, {})
    assert (tmp_path / "keep.txt").is_file()
