from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from coderking.tools.file import ReadFileTool
from coderking.tools.read import (
    IMAGE_SUFFIXES,
    MAX_TOTAL_BYTES,
    format_numbered_lines,
    read_path,
)


def test_format_numbered_lines() -> None:
    text = format_numbered_lines(["alpha", "beta"], offset=10)
    assert text == "10|alpha\n11|beta"


@pytest.mark.asyncio
async def test_read_single_file_with_line_numbers(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    result = await ReadFileTool(tmp_path).execute(path="a.py", offset=2, limit=2)
    assert result.ok
    assert "2|line2" in result.output
    assert "3|line3" in result.output
    assert "1|line1" not in result.output


@pytest.mark.asyncio
async def test_read_directory_glob(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a\n", encoding="utf-8")
    (tmp_path / "src" / "b.txt").write_text("b\n", encoding="utf-8")
    result = await ReadFileTool(tmp_path).execute(path="src", glob="*.py")
    assert result.ok
    assert "a.py" in result.output
    assert "b.txt" not in result.output


@pytest.mark.asyncio
async def test_read_image_returns_base64_block(tmp_path: Path) -> None:
    png = tmp_path / "pic.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 8)
    ok, output = read_path(tmp_path, str(png))
    assert ok
    payload = json.loads(output)
    assert payload["type"] == "image"
    assert payload["mime"] == "image/png"
    assert base64.b64decode(payload["base64"])


@pytest.mark.asyncio
async def test_read_binary_rejected(tmp_path: Path) -> None:
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02")
    result = await ReadFileTool(tmp_path).execute(path="bin.dat")
    assert not result.ok
    assert "binary" in result.output.lower()


def test_read_large_file_offset_limit_memory_safe(tmp_path: Path) -> None:
    path = tmp_path / "big.txt"
    with path.open("w", encoding="utf-8") as handle:
        for i in range(5000):
            handle.write(f"line-{i}\n")
    ok, output = read_path(tmp_path, "big.txt", offset=4000, limit=10)
    assert ok
    assert output.startswith("4000|line-3999")
    assert "4009|line-4008" in output
    assert "4010|" not in output
    assert len(output) < MAX_TOTAL_BYTES


def test_image_suffixes_cover_common_types() -> None:
    assert ".png" in IMAGE_SUFFIXES
    assert ".webp" in IMAGE_SUFFIXES
