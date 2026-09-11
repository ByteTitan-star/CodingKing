"""Session management: listing, resume pointer, and per-session save/load."""

from __future__ import annotations

import re
from pathlib import Path

from coderking.registry import (
    current_session_id,
    ensure_session,
    list_sessions,
    load_session,
    new_session_id,
    save_session,
    set_current_session_id,
)


def test_ensure_session_materializes_root(tmp_path: Path) -> None:
    sid = ensure_session(tmp_path, "s-20260911-140000")
    assert sid == "s-20260911-140000"
    metas = list_sessions(tmp_path)
    assert len(metas) == 1
    assert metas[0].session_id == "s-20260911-140000"
    assert metas[0].nodes == 1  # root only, no snapshot yet


def _snap(prompt: str, *, updated_hint: str = "", tokens: tuple[int, int] = (10, 20)) -> dict:
    return {
        "task_id": "t1",
        "prompt": prompt,
        "status": "succeeded",
        "role": "coding",
        "messages": [{"role": "user", "content": prompt}],
        "snapshot": {},
        "changed_files": [],
        "plan": [],
        "test_results": "1 passed",
        "last_test_ok": True,
        "iteration": 1,
        "token_input": tokens[0],
        "token_output": tokens[1],
    }


def test_new_session_id_is_timestamped_and_unique(tmp_path: Path) -> None:
    first = new_session_id(tmp_path)
    assert re.fullmatch(r"s-\d{8}-\d{6}", first), first
    ensure_session(tmp_path, first)
    second = new_session_id(tmp_path)
    assert second != first
    assert second.startswith(first)  # same second -> numeric suffix


def test_current_session_pointer_roundtrip(tmp_path: Path) -> None:
    assert current_session_id(tmp_path) == "default"
    set_current_session_id(tmp_path, "s-20260911-120000")
    assert current_session_id(tmp_path) == "s-20260911-120000"


def test_save_and_load_honour_explicit_session_id(tmp_path: Path) -> None:
    save_session(tmp_path, _snap("修复测试"), session_id="s-20260911-120000")
    assert load_session(tmp_path, "s-20260911-120000")["prompt"] == "修复测试"
    # default session is untouched
    assert load_session(tmp_path, "default") == {}


def test_load_session_follows_current_pointer(tmp_path: Path) -> None:
    save_session(tmp_path, _snap("task A"), session_id="default")
    save_session(tmp_path, _snap("task B"), session_id="s-20260911-130000")
    set_current_session_id(tmp_path, "s-20260911-130000")
    assert load_session(tmp_path)["prompt"] == "task B"
    set_current_session_id(tmp_path, "default")
    assert load_session(tmp_path)["prompt"] == "task A"


def test_list_sessions_reports_meta_newest_first(tmp_path: Path) -> None:
    save_session(tmp_path, _snap("第一个任务"), session_id="s-20260911-100000")
    save_session(tmp_path, _snap("第二个任务", tokens=(7, 9)), session_id="s-20260911-110000")
    metas = list_sessions(tmp_path)
    assert [m.session_id for m in metas] == ["s-20260911-110000", "s-20260911-100000"]
    newest = metas[0]
    assert newest.prompt == "第二个任务"
    assert newest.token_input == 7 and newest.token_output == 9
    assert newest.nodes >= 2  # root + snapshot
    assert metas[1].prompt == "第一个任务"


def test_list_sessions_tolerates_corrupt_tail(tmp_path: Path) -> None:
    save_session(tmp_path, _snap("正常会话"), session_id="s-20260911-090000")
    jsonl = tmp_path / ".coderking" / "sessions" / "s-20260911-090000.jsonl"
    with jsonl.open("a", encoding="utf-8") as handle:
        handle.write('{"id": "broken')
    metas = list_sessions(tmp_path)
    assert len(metas) == 1
    assert metas[0].prompt == "正常会话"
