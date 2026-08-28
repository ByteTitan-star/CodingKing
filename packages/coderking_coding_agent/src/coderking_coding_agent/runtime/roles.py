from __future__ import annotations

from coderking_coding_agent.runtime.state import Role

ROLE_TOOLS: dict[Role, frozenset[str]] = {
    Role.PLANNER: frozenset({"read_file", "search_code", "submit_plan"}),
    Role.CODING: frozenset(
        {
            "read_file",
            "write_file",
            "create_file",
            "edit_file",
            "search_code",
            "delete_file",
            "git_status",
            "git_diff",
            "submit_for_execution",
        }
    ),
    Role.EXECUTION: frozenset({"shell", "run_tests", "read_file"}),
    Role.REVIEWER: frozenset(
        {
            "read_file",
            "search_code",
            "git_diff",
            "git_status",
            "finish_task",
            "request_repair",
            "continue_execution",
        }
    ),
    Role.REPAIR: frozenset(
        {
            "read_file",
            "write_file",
            "create_file",
            "edit_file",
            "search_code",
            "delete_file",
            "shell",
            "run_tests",
            "git_diff",
            "submit_for_execution",
        }
    ),
}
