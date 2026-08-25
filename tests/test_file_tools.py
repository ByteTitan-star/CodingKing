from pathlib import Path

import pytest

from coderking.tools.file import ReadFileTool, WriteFileTool


@pytest.mark.asyncio
async def test_write_and_read(tmp_path: Path) -> None:
    await WriteFileTool(tmp_path).execute(path="pkg/mod.py", content="x = 1\n")
    result = await ReadFileTool(tmp_path).execute(path="pkg/mod.py")
    assert result.ok
    assert "x = 1" in result.output
