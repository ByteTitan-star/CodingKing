"""Interactive REPL input with slash-command completion (prompt_toolkit).

Shows a Claude-Code-style completion menu with descriptions when the user
types "/" — e.g. "/tr" matches /trace. Degrades gracefully: callers fall
back to plain rich input when prompt_toolkit is missing or stdin is not a
TTY (piped/CI usage).
"""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML

SLASH_COMMANDS: dict[str, str] = {
    "/new": "开始一条新会话（保留当前会话历史）",
    "/trace": "展开最近一次运行的工具调用轨迹",
    "/skills": "列出当前可用的 skills",
    "/skill:": "显式启用 skill，例如 /skill:review 检查这次改动",
    "/context": "查看上下文估算和自动压缩阈值",
    "/compact": "立即压缩当前会话上下文",
    "/exit": "退出会话（同 /quit 或 Ctrl+C）",
    "/quit": "退出会话",
}


class SlashCompleter(Completer):
    """Complete slash commands, displaying each command's description."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for name, description in SLASH_COMMANDS.items():
            if name.startswith(text):
                yield Completion(
                    name,
                    start_position=-len(text),
                    display=name,
                    display_meta=description,
                )


_session: PromptSession | None = None


def prompt() -> str:
    """Read one input line with completion; returns the stripped text."""
    global _session
    if _session is None:
        _session = PromptSession(
            HTML('<style fg="#D97757">❯ </style>'),
            completer=SlashCompleter(),
            complete_while_typing=True,
        )
    return _session.prompt().strip()
