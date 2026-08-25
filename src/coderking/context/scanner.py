from __future__ import annotations

from pathlib import Path

from coderking.workspace import SKIP_DIRS, iter_files


def scan_repository(workspace: Path, *, max_tree: int = 80) -> str:
    root = workspace.resolve()
    lines: list[str] = [f"workspace: {root}"]
    readme = _first_readme(root)
    if readme:
        lines.append("README excerpt:")
        lines.append(readme[:2500])
    deps = _dependency_files(root)
    if deps:
        lines.append("dependency files: " + ", ".join(deps))
    tests = [p.relative_to(root).as_posix() for p in iter_files(root) if "test" in p.name.lower()]
    if tests:
        lines.append("test files: " + ", ".join(tests[:20]))
    lines.append("tree:")
    count = 0
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        lines.append(f"  {rel}")
        count += 1
        if count >= max_tree:
            lines.append("  ...")
            break
    return "\n".join(lines)


def _first_readme(root: Path) -> str | None:
    for name in ("README.md", "README.rst", "README.txt", "README"):
        path = root / name
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return None


def _dependency_files(root: Path) -> list[str]:
    names = [
        "pyproject.toml",
        "requirements.txt",
        "package.json",
        "go.mod",
        "Cargo.toml",
        "pom.xml",
    ]
    return [name for name in names if (root / name).is_file()]
