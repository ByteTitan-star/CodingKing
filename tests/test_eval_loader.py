from pathlib import Path

from coderking.evalkit.loader import discover_tasks


def test_discover_three_categories() -> None:
    root = Path(__file__).resolve().parents[1] / "eval" / "tasks"
    tasks = discover_tasks(root)
    cats = {task.category for task, _ in tasks}
    ids = {task.task_id for task, _ in tasks}
    assert {"bug_fix", "feature_add", "refactor"} <= cats
    assert "bug_fix_add" in ids
    assert "feature_add_greet" in ids
    assert "refactor_area" in ids
