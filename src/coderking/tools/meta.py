from __future__ import annotations

from typing import Any

from coderking.tools.base import Tool, ToolResult


class MetaTool(Tool):
    def __init__(self, name: str, description: str, parameters: dict[str, Any]):
        self.name = name
        self.description = description
        self.parameters = parameters

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(True, "", changed_file=None)


def meta_tools() -> list[Tool]:
    return [
        MetaTool(
            "submit_plan",
            "Submit the execution plan as a list of step titles.",
            {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["steps"],
            },
        ),
        MetaTool(
            "submit_for_execution",
            "Hand off to the Execution role to run tests/builds.",
            {"type": "object", "properties": {}},
        ),
        MetaTool(
            "finish_task",
            "Mark the task as successfully completed.",
            {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        ),
        MetaTool(
            "request_repair",
            "Send the task to Repair with a failure reason.",
            {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        ),
        MetaTool(
            "continue_execution",
            "Reviewer: send the task back to Execution to run tests or commands again.",
            {"type": "object", "properties": {}},
        ),
    ]
