from __future__ import annotations

import textwrap
from pathlib import Path

from check_layer_deps import LAYER_ALLOW, check_all, check_file


def test_layer_allow_graph_is_acyclic_and_downward_only() -> None:
    # L0 → nothing; each upper layer may only import layers below it.
    assert LAYER_ALLOW["coderking_llm"] == frozenset()
    assert "coderking_transport" not in LAYER_ALLOW["coderking_coding_agent"]
    assert "coderking_coding_agent" not in LAYER_ALLOW["coderking_agent_core"]
    assert "coderking_agent_core" not in LAYER_ALLOW["coderking_llm"]


def test_check_file_rejects_upward_import(tmp_path: Path) -> None:
    path = tmp_path / "bad.py"
    path.write_text(
        textwrap.dedent(
            """
            from coderking_transport import something
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    violations = check_file(path, "coderking_llm")
    assert violations
    assert "coderking_transport" in violations[0]


def test_check_file_allows_downward_import(tmp_path: Path) -> None:
    path = tmp_path / "ok.py"
    path.write_text(
        textwrap.dedent(
            """
            from coderking_llm import LAYER
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    assert check_file(path, "coderking_agent_core") == []


def test_packages_tree_passes_boundary_check() -> None:
    assert check_all() == []
