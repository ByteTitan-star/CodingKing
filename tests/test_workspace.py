from pathlib import Path

import pytest

from coderking.workspace import ensure_inside


def test_ensure_inside_allows_relative(tmp_path: Path) -> None:
    target = ensure_inside(tmp_path, Path("a/b.txt"))
    assert target == (tmp_path / "a" / "b.txt").resolve()


def test_ensure_inside_blocks_escape(tmp_path: Path) -> None:
    with pytest.raises(PermissionError):
        ensure_inside(tmp_path, Path("../secret.txt"))
