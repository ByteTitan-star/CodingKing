from pathlib import Path

from coderking.context.bm25 import BM25Index


def test_bm25_ranks_relevant_file(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text(
        "def login(user, password):\n    return jwt_token\n", encoding="utf-8"
    )
    (tmp_path / "readme.txt").write_text("unrelated vegetables", encoding="utf-8")
    hits = BM25Index(tmp_path).search("jwt login authentication")
    assert hits
    assert hits[0][0] == "auth.py"
