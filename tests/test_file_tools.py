from pathlib import Path

import pytest

from coderking.tools.file import ReadFileTool, WriteFileTool, invalidate_bytecode


@pytest.mark.asyncio
async def test_write_and_read(tmp_path: Path) -> None:
    await WriteFileTool(tmp_path).execute(path="pkg/mod.py", content="x = 1\n")
    result = await ReadFileTool(tmp_path).execute(path="pkg/mod.py")
    assert result.ok
    assert "x = 1" in result.output


@pytest.mark.asyncio
async def test_write_file_drops_stale_pyc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rewriting a module within the same second must not leave stale bytecode.

    CPython matches cached bytecode by (whole-second mtime, size); a same-second
    rewrite of equal length keeps the old .pyc "valid", so later imports run the
    outdated code. write_file must invalidate the cache.
    """
    import sys

    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    import calc  # noqa: F401  (compiles and caches bytecode)

    sys.modules.pop("calc", None)
    stale_glob = "__pycache__/calc.cpython-*.pyc"
    assert list(tmp_path.glob(stale_glob)), "expected a cached .pyc after import"

    await WriteFileTool(tmp_path).execute(
        path="calc.py", content="def add(a, b):\n    return a + b\n"
    )
    assert not list(tmp_path.glob(stale_glob)), "write_file must drop stale __pycache__ entries"


def test_invalidate_bytecode_ignores_non_python(tmp_path: Path) -> None:
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "notes.txt").write_text("x", encoding="utf-8")
    invalidate_bytecode(tmp_path / "notes.txt")
    assert (tmp_path / "__pycache__" / "notes.txt").is_file()
