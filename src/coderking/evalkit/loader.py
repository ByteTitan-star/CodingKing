from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class EvalTask(BaseModel):
    task_id: str
    repository: str
    instruction: str
    expected_result: str
    test_command: str
    category: str = Field(default="")

    def repo_path(self, task_dir: Path) -> Path:
        return (task_dir / self.repository).resolve()


def load_task(task_json: Path) -> tuple[EvalTask, Path]:
    data = json.loads(task_json.read_text(encoding="utf-8"))
    task = EvalTask.model_validate(data)
    task_dir = task_json.parent
    if not task.category:
        task.category = task_dir.parent.name
    return task, task_dir


def discover_tasks(root: Path) -> list[tuple[EvalTask, Path]]:
    found: list[tuple[EvalTask, Path]] = []
    for path in sorted(root.glob("**/task.json")):
        found.append(load_task(path))
    return found
