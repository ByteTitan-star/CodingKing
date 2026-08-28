from __future__ import annotations

import json
import time
from pathlib import Path

from coderking_coding_agent.session import SessionRepo, import_legacy_session


def test_branch_keeps_both_paths(tmp_path: Path) -> None:
    repo = SessionRepo(tmp_path)
    root_id = repo.head_id
    assert root_id is not None

    repo.append("message", {"message": {"role": "user", "content": "A"}})
    b = repo.append("message", {"message": {"role": "assistant", "content": "B"}})

    repo.branch_to(root_id)
    repo.append("message", {"message": {"role": "user", "content": "C"}})

    path_main = [n.payload.get("message", {}).get("content") for n in repo.walk_to_head()]
    assert path_main == [None, "C"]

    repo.branch_to(b.id)
    path_alt = [n.payload.get("message", {}).get("content") for n in repo.walk_to_head()]
    assert path_alt == [None, "A", "B"]

    lines = repo.jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4
    assert '"content":"A"' in repo.jsonl_path.read_text(encoding="utf-8")
    assert '"content":"B"' in repo.jsonl_path.read_text(encoding="utf-8")


def test_recover_truncates_corrupt_tail(tmp_path: Path) -> None:
    repo = SessionRepo(tmp_path)
    repo.append("message", {"message": {"role": "user", "content": "ok"}})
    with repo.jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write("{{not json\n")

    repo2 = SessionRepo(tmp_path)
    chain = repo2.walk_to_head()
    assert any(n.payload.get("message", {}).get("content") == "ok" for n in chain)
    assert "{{not json" not in repo2.jsonl_path.read_text(encoding="utf-8")


def test_walk_10k_nodes_fast(tmp_path: Path) -> None:
    repo = SessionRepo(tmp_path)
    parent_id = repo.head_id
    assert parent_id is not None
    lines: list[str] = []
    last_id = parent_id
    for i in range(10_000):
        node_id = f"n{i:05d}"
        node = {
            "id": node_id,
            "parent_id": last_id,
            "kind": "message",
            "payload": {"message": {"role": "user", "content": str(i)}},
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        lines.append(json.dumps(node, separators=(",", ":")))
        last_id = node_id
    with repo.jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    repo.head_path.write_text(json.dumps({"head_id": last_id}), encoding="utf-8")

    repo2 = SessionRepo(tmp_path)
    start = time.perf_counter()
    chain = repo2.walk_to_head()
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert len(chain) == 10_001
    assert elapsed_ms < 50, f"walk_to_head took {elapsed_ms:.1f}ms"


def test_import_legacy_session_json(tmp_path: Path) -> None:
    legacy = tmp_path / ".coderking" / "session.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps(
            {
                "task_id": "t1",
                "prompt": "hello",
                "messages": [{"role": "user", "content": "hi"}],
            }
        ),
        encoding="utf-8",
    )
    repo = import_legacy_session(tmp_path)
    assert repo is not None
    state = repo.materialize_session_state()
    assert state.get("task_id") == "t1"
    msgs = repo.materialize_messages()
    assert msgs == [{"role": "user", "content": "hi"}]


def test_registry_load_save_uses_jsonl(tmp_path: Path) -> None:
    from coderking import registry

    (tmp_path / ".coderking").mkdir(parents=True, exist_ok=True)
    payload = {"task_id": "x", "prompt": "p", "messages": []}
    registry.save_session(tmp_path, payload)
    assert registry.session_jsonl_path(tmp_path).is_file()
    loaded = registry.load_session(tmp_path)
    assert loaded.get("task_id") == "x"
