from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class Role(StrEnum):
    PLANNER = "planner"
    CODING = "coding"
    EXECUTION = "execution"
    REVIEWER = "reviewer"
    REPAIR = "repair"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass
class PlanItem:
    title: str
    done: bool = False


@dataclass
class ToolRecord:
    name: str
    arguments: dict[str, Any]
    output: str
    ok: bool
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class AgentState:
    task: str
    repository: str
    task_id: str = field(default_factory=lambda: uuid4().hex[:12])
    role: Role = Role.PLANNER
    status: TaskStatus = TaskStatus.PENDING
    plan: list[PlanItem] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_history: list[ToolRecord] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    test_results: str = ""
    errors: list[str] = field(default_factory=list)
    iteration: int = 0
    token_input: int = 0
    token_output: int = 0
    sandbox_backend: str = "unknown"
    sandbox_status: str = "idle"
    last_test_ok: bool | None = None
    repair_count: int = 0
    snapshot: dict[str, str | None] = field(default_factory=dict)
    cancel_requested: bool = False

    def mark_file(self, rel: str) -> None:
        if rel not in self.changed_files:
            self.changed_files.append(rel)

    def mark_next_plan_item(self) -> None:
        for item in self.plan:
            if not item.done:
                item.done = True
                return

    def mark_plan_complete(self) -> None:
        for item in self.plan:
            item.done = True
