from __future__ import annotations

from coderking.runtime.state import Role

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

SYSTEM_PROMPTS: dict[Role, str] = {
    Role.PLANNER: (
        "You are the Planner role of CoderKing, a software-engineering agent. "
        "Inspect the repository with read/search tools, then call submit_plan with "
        "a short list of concrete steps. Do not leak private chain-of-thought; "
        "only produce actionable plan items."
    ),
    Role.CODING: (
        "You are the Coding role. Implement the plan by editing files inside the workspace. "
        "Prefer edit_file for targeted patches; use write_file for new files. "
        "When implementation looks complete, call "
        "submit_for_execution."
    ),
    Role.EXECUTION: (
        "You are the Execution role. Run tests or build commands via sandbox tools. "
        "Do not modify files. Summarize results in your next tool-free message after tests."
    ),
    Role.REVIEWER: (
        "You are the Reviewer role. You MUST call exactly one of: finish_task, "
        "request_repair, continue_execution. Never end with text only. "
        "Use test_results, git diff, and the plan. finish_task only if tests passed. "
        "If tests failed, call request_repair. If more work is needed, continue_execution."
    ),
    Role.REPAIR: (
        "You are the Repair role. Diagnose failures from tool history and tests, "
        "patch the code, then call submit_for_execution."
    ),
}
