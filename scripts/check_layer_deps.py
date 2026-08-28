"""Enforce v2 layer import boundaries (Pi-style monorepo)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES_SRC = ROOT / "packages"

# Package import name → allowed imports of other layer packages.
# Facade `coderking` is scanned separately once code migrates; PR-1 only
# enforces packages/* boundaries.
LAYER_ALLOW: dict[str, frozenset[str]] = {
    "coderking_llm": frozenset(),
    "coderking_agent_core": frozenset({"coderking_llm"}),
    "coderking_coding_agent": frozenset({"coderking_llm", "coderking_agent_core"}),
    "coderking_transport": frozenset(
        {"coderking_llm", "coderking_agent_core", "coderking_coding_agent"}
    ),
}

LAYER_PACKAGES = frozenset(LAYER_ALLOW)


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def check_file(path: Path, package: str) -> list[str]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: syntax error: {exc}"]

    allowed = LAYER_ALLOW[package]
    violations: list[str] = []
    for root in sorted(_imported_roots(tree)):
        if root not in LAYER_PACKAGES or root == package:
            continue
        if root not in allowed:
            try:
                rel = path.relative_to(ROOT).as_posix()
            except ValueError:
                rel = path.as_posix()
            violations.append(
                f"{rel}: package {package!r} must not import {root!r} "
                f"(allowed: {sorted(allowed) or 'none'})"
            )
    return violations


def iter_package_modules() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    if not PACKAGES_SRC.is_dir():
        return found
    for pkg_dir in sorted(PACKAGES_SRC.iterdir()):
        if not pkg_dir.is_dir():
            continue
        name = pkg_dir.name
        if name not in LAYER_ALLOW:
            continue
        src_root = pkg_dir / "src" / name
        if not src_root.is_dir():
            continue
        for path in src_root.rglob("*.py"):
            found.append((name, path))
    return found


def check_all() -> list[str]:
    errors: list[str] = []
    for package, path in iter_package_modules():
        errors.extend(check_file(path, package))
    return errors


def main() -> int:
    errors = check_all()
    if errors:
        print("Layer dependency violations:", file=sys.stderr)
        for item in errors:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"OK: checked {len(iter_package_modules())} modules across {len(LAYER_ALLOW)} layers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
