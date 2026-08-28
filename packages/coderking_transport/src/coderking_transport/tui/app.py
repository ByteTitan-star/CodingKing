"""Textual TUI for CoderKing agent sessions."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, RichLog, Static, TextArea

from coderking_transport.tui.event_log import ScrollbackLog
from coderking_transport.tui.formatters import format_agent_event
from coderking_transport.tui.session import TuiAgentSession


class CoderKingTuiApp(App[None]):
    """Retained-mode panels: chat, tool trace, terminal, status."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #status-bar {
        height: 3;
        padding: 0 1;
        background: $surface;
    }
    #body {
        height: 1fr;
    }
    #chat-log {
        width: 2fr;
        border: solid $primary;
    }
    #side-panels {
        width: 1fr;
    }
    #tools-log {
        height: 1fr;
        border: solid $secondary;
    }
    #terminal-log {
        height: 1fr;
        border: solid $accent;
    }
    #input-area {
        height: 7;
        border: solid $primary-darken-2;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+enter", "submit_prompt", "Submit", show=True),
        Binding("ctrl+s", "submit_steer", "Steer", show=True),
        Binding("ctrl+a", "abort_task", "Abort", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
    ]

    def __init__(
        self,
        session: TuiAgentSession,
        *,
        workspace_label: str = ".",
    ) -> None:
        super().__init__()
        self.session = session
        self.workspace_label = workspace_label
        self._task_id: str | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._steer_mode = False
        self._buffers: dict[str, ScrollbackLog] = {
            "chat": ScrollbackLog(),
            "tools": ScrollbackLog(),
            "terminal": ScrollbackLog(),
        }
        self._status = "idle"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._status_text(), id="status-bar")
        with Horizontal(id="body"):
            yield RichLog(id="chat-log", wrap=True, markup=True, highlight=True)
            with Vertical(id="side-panels"):
                yield RichLog(id="tools-log", wrap=True, markup=True, highlight=True)
                yield RichLog(id="terminal-log", wrap=True, markup=True, highlight=True)
        yield TextArea(id="input-area", language="markdown", show_line_numbers=False)
        yield Footer()

    def _status_text(self) -> str:
        mode = "STEER" if self._steer_mode else "PROMPT"
        task = self._task_id or "—"
        return f"workspace={self.workspace_label}  task={task}  mode={mode}  {self._status}"

    def _update_status_bar(self) -> None:
        self.query_one("#status-bar", Static).update(self._status_text())

    def _write_panel(self, panel: str, line: str) -> None:
        buffer = self._buffers.get(panel)
        if buffer is not None:
            buffer.append(line)
        widget_id = {
            "chat": "#chat-log",
            "tools": "#tools-log",
            "terminal": "#terminal-log",
        }.get(panel)
        if widget_id:
            self.query_one(widget_id, RichLog).write(line)

    def _render_record(self, record: dict[str, Any]) -> None:
        formatted = format_agent_event(record)
        if formatted is None:
            return
        panel, line = formatted
        if panel == "status":
            self._status = line
            self._update_status_bar()
            return
        self._write_panel(panel, line)

    async def action_submit_prompt(self) -> None:
        if self._steer_mode:
            await self.action_submit_steer()
            return
        area = self.query_one("#input-area", TextArea)
        text = area.text.strip()
        if not text:
            return
        area.clear()
        self._write_panel("chat", f"[bold cyan]you[/bold cyan] {text}")
        if self._run_task is not None and not self._run_task.done():
            self.notify("Task already running — use Ctrl+S to steer", severity="warning")
            return
        self._run_task = asyncio.create_task(self._run_agent(text))

    async def action_submit_steer(self) -> None:
        area = self.query_one("#input-area", TextArea)
        text = area.text.strip()
        if not text:
            self._steer_mode = not self._steer_mode
            self._update_status_bar()
            self.notify(
                "Steer mode ON — Enter steers running task"
                if self._steer_mode
                else "Steer mode OFF"
            )
            return
        if not self._task_id:
            self.notify("No active task to steer", severity="error")
            return
        area.clear()
        self._write_panel("chat", f"[bold yellow]steer[/bold yellow] {text}")
        await self.session.steer(self._task_id, text)

    async def action_abort_task(self) -> None:
        if not self._task_id:
            self.notify("No active task", severity="warning")
            return
        await self.session.abort(self._task_id)
        self.notify("Abort requested")

    async def _run_agent(self, prompt: str) -> None:
        self._status = "starting…"
        self._update_status_bar()
        try:
            self._task_id = await self.session.start(prompt)
            self._status = "running"
            self._update_status_bar()
            async for record in self.session.events(self._task_id):
                self._render_record(record)
        except asyncio.CancelledError:
            self._status = "cancelled"
            self._write_panel("chat", "[cancelled]")
        except Exception as exc:
            self._status = "error"
            self._write_panel("chat", f"[error] {exc}")
        finally:
            self._status = "idle"
            self._update_status_bar()

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        if not self._steer_mode or not self._task_id:
            return
        area = self.query_one("#input-area", TextArea)
        text = area.text
        if not text.endswith("\n"):
            return
        payload = text.strip()
        area.clear()
        if not payload:
            return
        asyncio.create_task(self._steer_from_enter(payload))

    async def _steer_from_enter(self, text: str) -> None:
        self._write_panel("chat", f"[bold yellow]steer[/bold yellow] {text}")
        await self.session.steer(self._task_id, text)


async def run_tui_app(session: TuiAgentSession, *, workspace_label: str = ".") -> None:
    app = CoderKingTuiApp(session, workspace_label=workspace_label)
    await app.run_async()
