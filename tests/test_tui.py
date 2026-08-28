from __future__ import annotations

from coderking_transport.tui.event_log import ScrollbackLog
from coderking_transport.tui.formatters import format_agent_event


def test_scrollback_log_caps_at_max_lines() -> None:
    log = ScrollbackLog(max_lines=3)
    log.extend(["a", "b", "c", "d"])
    assert log.lines() == ["b", "c", "d"]
    assert len(log) == 3


def test_scrollback_log_supports_10k_default() -> None:
    log = ScrollbackLog()
    log.extend([str(i) for i in range(10_500)])
    assert len(log) == 10_000
    assert log.tail(1) == ["10499"]


def test_format_tool_call_to_tools_panel() -> None:
    formatted = format_agent_event(
        {"type": "tool_call", "payload": {"tool": "read_file", "status": "running"}}
    )
    assert formatted == ("tools", "read_file [running]")


def test_format_phase_change_to_status() -> None:
    formatted = format_agent_event(
        {"type": "phase_change", "payload": {"phase": "decide", "from": "perceive"}}
    )
    assert formatted == ("status", "phase perceive → decide")


def test_format_done_to_chat() -> None:
    formatted = format_agent_event(
        {"type": "done", "payload": {"ok": True, "summary": "fixed tests"}}
    )
    assert formatted is not None
    panel, line = formatted
    assert panel == "chat"
    assert "fixed tests" in line


def test_format_terminal_strips_empty() -> None:
    assert format_agent_event({"type": "terminal", "payload": {"text": "  "}}) is None
