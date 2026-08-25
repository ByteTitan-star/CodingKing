from coderking.runtime.roles import ROLE_TOOLS, Role


def test_planner_cannot_shell() -> None:
    assert "shell" not in ROLE_TOOLS[Role.PLANNER]
    assert "write_file" in ROLE_TOOLS[Role.CODING]
    assert "finish_task" in ROLE_TOOLS[Role.REVIEWER]
    assert "continue_execution" in ROLE_TOOLS[Role.REVIEWER]
    assert "request_repair" in ROLE_TOOLS[Role.REVIEWER]
