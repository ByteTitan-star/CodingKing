from pathlib import Path

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
