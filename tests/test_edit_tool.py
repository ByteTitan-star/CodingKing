from pathlib import Path

import pytest

from coderking.tools.edit import EditFileTool, apply_string_replace


def test_apply_unique_replace() -> None:
    text = "alpha\nbeta\ngamma\n"
    new_text, info = apply_string_replace(text, "beta", "BETA")
    assert new_text == "alpha\nBETA\ngamma\n"
    assert info.match_count == 1
    assert info.used_fuzzy is False


def test_apply_zero_matches_raises() -> None:
    with pytest.raises(ValueError, match="0 occurrences"):
        apply_string_replace("hello", "missing", "x")


def test_apply_multiple_matches_raises_without_replace_all() -> None:
    with pytest.raises(ValueError, match="2 occurrences"):
        apply_string_replace("foo foo", "foo", "bar")


def test_apply_replace_all() -> None:
    new_text, info = apply_string_replace("foo foo", "foo", "bar", replace_all=True)
    assert new_text == "bar bar"
    assert info.match_count == 2


def test_apply_fuzzy_whitespace_match() -> None:
    text = "def x():\n    return 1\n"
    old = "def x():\n\treturn 1"
    new_text, info = apply_string_replace(text, old, "def x():\n    return 2")
    assert "return 2" in new_text
    assert info.used_fuzzy is True


@pytest.mark.asyncio
async def test_edit_file_tool_writes_and_invalidates_pyc(tmp_path: Path) -> None:
    path = tmp_path / "calc.py"
    path.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "calc.cpython-312.pyc").write_bytes(b"stale")

    result = await EditFileTool(tmp_path).execute(
        path="calc.py",
        old_string="return a - b",
        new_string="return a + b",
    )
    assert result.ok
    assert "+ b" in path.read_text(encoding="utf-8")
    assert result.changed_file == "calc.py"
    assert not list((tmp_path / "__pycache__").glob("calc.*.pyc"))


@pytest.mark.asyncio
async def test_edit_file_rejects_ambiguous_match(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x=1\nx=1\n", encoding="utf-8")
    result = await EditFileTool(tmp_path).execute(path="a.py", old_string="x=1", new_string="x=2")
    assert not result.ok
    assert "2 occurrences" in result.output
