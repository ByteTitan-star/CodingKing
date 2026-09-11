"""Rich theme + render helpers for the coderking CLI.

Design language follows Claude Code / Hermes: dark-terminal friendly,
single terracotta accent, dim metadata, no panel spam.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.rule import Rule
from rich.theme import Theme

from coderking import __version__
from coderking.runtime.state import AgentState, TaskStatus

BRAND_MARK = "✻"

# Warm dark-terminal palette (Claude terracotta accent).
C = {
    "brand": "#D97757",  # terracotta — brand + emphasis
    "brand_dim": "#B0634A",
    "dim": "#8B867C",  # warm gray — metadata, hints
    "faint": "#6B665E",  # deeper gray — bulk terminal output
    "text": "#E8E4DC",  # warm off-white
    "ok": "#57A773",  # soft green
    "err": "#E06C5F",  # soft red
    "warn": "#D9A05B",  # soft amber
    "info": "#7FA8D9",  # soft blue
}

THEME = Theme(
    {
        "ck.brand": f"bold {C['brand']}",
        "ck.accent": C["brand"],
        "ck.dim": C["dim"],
        "ck.faint": C["faint"],
        "ck.ok": C["ok"],
        "ck.err": C["err"],
        "ck.warn": C["warn"],
        "ck.info": C["info"],
    }
)

console = Console(theme=THEME)

_STATUS_STYLE = {
    TaskStatus.SUCCEEDED: ("完成", "ck.ok"),
    TaskStatus.FAILED: ("失败", "ck.err"),
    TaskStatus.INTERRUPTED: ("已中断", "ck.warn"),
    TaskStatus.RUNNING: ("运行中", "ck.warn"),
    TaskStatus.WAITING_APPROVAL: ("等待确认", "ck.warn"),
    TaskStatus.PENDING: ("待运行", "ck.dim"),
}


def _style_typer_help() -> None:
    """Nudge Typer/click rich-help colors toward our palette (best effort)."""
    try:  # pragma: no cover - cosmetic only
        from typer.core import rich_utils

        rich_utils.STYLE_HELPTEXT = ""
        rich_utils.STYLE_OPTIONS_PANEL_BORDER = C["brand_dim"]
        rich_utils.STYLE_OPTIONS_TABLE_BOX = ""
        rich_utils.STYLE_COMMANDS_PANEL_BORDER = C["brand_dim"]
        rich_utils.STYLE_COMMANDS_TABLE_BOX = ""
    except Exception:
        pass


_style_typer_help()


def print_banner(
    *,
    workspace: Path,
    model: str,
    sandbox: str = "auto",
    interactive: bool = True,
    show_brand: bool = True,
) -> None:
    """Claude-Code-style welcome: mark, product, two dim meta lines, hint."""
    console.print()
    if show_brand:
        brand = f"[ck.brand]{BRAND_MARK} CoderKing[/ck.brand] [ck.dim]v{__version__}[/ck.dim]"
        console.print(brand)
        console.print()
    home = str(workspace)
    if home.startswith(str(Path.home())):
        home = "~" + home[len(str(Path.home())) :]
    console.print(f"  [ck.dim]工作区[/ck.dim]  {home}")
    console.print(f"  [ck.dim]模型[/ck.dim]    {model} · 沙箱 {sandbox}")
    console.print()
    if interactive:
        hint = "  输入任务开始 · /new 新会话 · /trace 工具轨迹 · /exit 退出"
        console.print(f"[ck.faint]{hint}[/ck.faint]")
    console.print()


def spinner_label(index: int) -> str:
    """Rotating status verbs for the Live line (Claude Code style)."""
    verbs = ("思考中", "读取文件", "分析代码", "编辑文件", "运行检查", "验证结果")
    return verbs[index % len(verbs)]


_TOOL_MARK = {
    "read": "读",
    "write": "写",
    "edit": "改",
    "bash": "跑",
}


def print_run_event(payload: dict) -> str:
    """Format one runtime event as a single dim line; returns the rich markup."""
    etype = str(payload.get("type") or "")
    if etype == "tool_call":
        tool = str(payload.get("tool") or "?")
        mark = _TOOL_MARK.get(tool, "调")
        status = str(payload.get("status") or "")
        args = payload.get("arguments") or payload.get("preview") or ""
        arg = str(args)[:60]
        suffix = ""
        if status == "ok":
            suffix = " [ck.ok]✓[/ck.ok]"
        elif status == "error":
            suffix = " [ck.err]✗[/ck.err]"
        head = f"[ck.faint]⏺ {mark}[/ck.faint] {escape(tool)} [ck.faint]{escape(arg)}[/ck.faint]"
        return head + suffix
    if etype == "terminal":
        text = escape(str(payload.get("text", ""))[:120].strip())
        return f"[ck.faint]│ {text}[/ck.faint]"
    if etype == "approval_required":
        tool = escape(str(payload.get("tool") or "?"))
        return f"[ck.warn]⏸ 需要确认：{tool}[/ck.warn]"
    return ""


def print_state(state: AgentState) -> None:
    """Final summary: mark + status word, then three dim key-value lines."""
    label, style = _STATUS_STYLE.get(state.status, (state.status.value, "ck.dim"))
    console.print(Rule(characters="─", style=C["brand_dim"]))
    console.print(f"[{style}]{BRAND_MARK} {label}[/]")
    console.print(f"  [ck.dim]任务[/ck.dim]  {escape(state.task[:80])}")
    if state.changed_files:
        shown = "、".join(state.changed_files[:4])
        more = f" 等 {len(state.changed_files)} 个文件" if len(state.changed_files) > 4 else ""
        console.print(f"  [ck.dim]文件[/ck.dim]  {escape(shown)}{more}")
    if state.test_results:
        passed = state.test_results.split("\n")[0][:80]
        icon = "[ck.ok]✓[/ck.ok]" if state.last_test_ok else "[ck.err]✗[/ck.err]"
        console.print(f"  [ck.dim]测试[/ck.dim]  {icon} {escape(passed)}")
    tokens = f"{state.token_input} → {state.token_output} tokens"
    console.print(f"  [ck.dim]用量[/ck.dim]  {tokens} · 迭代 {state.iteration}")
    console.print(Rule(characters="─", style=C["brand_dim"]))
