from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import uvicorn
from rich.live import Live
from rich.table import Table
from rich.text import Text

from coderking import __version__
from coderking.config import config_yaml_path, load_settings, write_yaml_config
from coderking.evalkit.loader import discover_tasks
from coderking.evalkit.runner import run_suite, summarize, write_reports
from coderking.llm.openai_compat import OpenAICompatProvider
from coderking.registry import (
    current_session_id,
    ensure_session,
    list_sessions,
    load_current,
    load_session,
    new_session_id,
    request_cancel,
    save_session,
    set_current_session_id,
)
from coderking.runtime.cancel import CancellationToken
from coderking.runtime.events import AgentEvent
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import AgentState, PlanItem, Role, TaskStatus
from coderking.sandbox.local import LocalProcessSandbox
from coderking.ui.splash import play_splash
from coderking.ui.theme import (
    BRAND_MARK,
    console,
    print_banner,
    print_run_event,
    print_state,
    spinner_label,
)

app = typer.Typer(no_args_is_help=True, add_completion=False, help="CoderKing coding agent CLI")
config_app = typer.Typer(no_args_is_help=True, help="Configure models and runtime")
app.add_typer(config_app, name="config")


def _workspace(path: Path | None) -> Path:
    return (path or Path.cwd()).resolve()


@app.callback()
def _version_option(
    version: bool = typer.Option(False, "--version", help="Show version and exit"),
) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()


@app.command()
def init(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Create .coderking/config.yaml, policy.yaml, and AGENTS.md template in the workspace."""
    root = _workspace(workspace)
    (root / ".coderking" / "memory").mkdir(parents=True, exist_ok=True)
    tools_root = root / ".coderking" / "tools"
    tools_root.mkdir(parents=True, exist_ok=True)
    example = tools_root / "browser_smoke"
    if not example.exists():
        template_root = Path(__file__).resolve().parent / "templates" / "tools" / "browser_smoke"
        if template_root.is_dir():
            example.mkdir(parents=True, exist_ok=True)
            for name in ("tool.yaml", "main.py"):
                src = template_root / name
                if src.is_file():
                    (example / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            console.print(f"created example dynamic tool at {example}")
    if not config_yaml_path(root).exists():
        write_yaml_config(
            root,
            {
                "model": "deepseek-chat",
                "sandbox_mode": "auto",
                "allow_commit": False,
                "max_iterations": 24,
            },
        )
    policy_path = root / ".coderking" / "policy.yaml"
    if not policy_path.exists():
        template = (Path(__file__).resolve().parent / "templates" / "policy.yaml").read_text(
            encoding="utf-8"
        )
        policy_path.write_text(template, encoding="utf-8")
        console.print(f"created {policy_path}")
    agents_path = root / "AGENTS.md"
    if not agents_path.exists():
        template = (Path(__file__).resolve().parent / "templates" / "AGENTS.md").read_text(
            encoding="utf-8"
        )
        agents_path.write_text(template, encoding="utf-8")
        console.print(f"created {agents_path}")
    console.print(f"initialized {root / '.coderking'}")


@app.command()
def rpc(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """JSON-RPC 2.0 over stdin/stdout for Desktop/automation (Pi-style)."""
    from coderking.rpc import run_rpc_server

    asyncio.run(run_rpc_server(_workspace(workspace)))


@app.command()
def tui(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", help="Auto-approve dangerous tools"),
    commit: bool = typer.Option(False, "--commit", help="Allow git_commit"),
) -> None:
    """Interactive Textual TUI (chat / tools / terminal panels)."""
    from coderking.tui_runner import run_interactive_tui

    root = _workspace(workspace)
    settings = load_settings(workspace=root, allow_commit=commit)
    asyncio.run(run_interactive_tui(root, settings, auto_approve=yes))


@app.command()
def run(
    prompt: str = typer.Argument(..., help="Natural language engineering task"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", help="Auto-approve dangerous tools"),
    commit: bool = typer.Option(False, "--commit", help="Allow git_commit"),
    test: str | None = typer.Option(
        None,
        "--test",
        help="Preferred verification command (soft prompt hint for bash)",
    ),
) -> None:
    """Run the agent against a repository (in-process Runtime, same as Web)."""
    settings = load_settings(workspace=_workspace(workspace), allow_commit=commit)
    print_banner(
        workspace=settings.resolved_workspace(),
        model=settings.model,
        sandbox=settings.sandbox_mode,
        interactive=False,
    )
    asyncio.run(_run_task(prompt, settings, auto_approve=yes, resume=None, test_command=test))


@app.command()
def chat(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes"),
    commit: bool = typer.Option(False, "--commit"),
    test: str | None = typer.Option(
        None,
        "--test",
        help="Preferred verification command (soft prompt hint for bash)",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        "-r",
        help="Pick a past session to resume (interactive picker)",
    ),
    resume_index: int | None = typer.Option(
        None,
        "--resume-index",
        help="Resume the Nth session from `codeking sessions` directly",
    ),
) -> None:
    """Interactive session that continues on the same workspace."""
    root = _workspace(workspace)
    settings = load_settings(workspace=root, allow_commit=commit)
    session_id = current_session_id(root)
    if resume or resume_index is not None:
        picked = _resolve_resume(root, resume_index)
        if picked is None:
            return
        session_id = picked
        set_current_session_id(root, session_id)
    played = play_splash(console)
    print_banner(
        workspace=root,
        model=settings.model,
        sandbox=settings.sandbox_mode,
        interactive=True,
        show_brand=not played,
    )
    _chat_loop(root, settings, yes, test, session_id)


@app.command()
def new(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes"),
    commit: bool = typer.Option(False, "--commit"),
    test: str | None = typer.Option(
        None,
        "--test",
        help="Preferred verification command (soft prompt hint for bash)",
    ),
) -> None:
    """Start a fresh session on the workspace (keeps old ones)."""
    root = _workspace(workspace)
    settings = load_settings(workspace=root, allow_commit=commit)
    session_id = new_session_id(root)
    set_current_session_id(root, session_id)
    played = play_splash(console)
    print_banner(
        workspace=root,
        model=settings.model,
        sandbox=settings.sandbox_mode,
        interactive=True,
        show_brand=not played,
    )
    console.print(f"[ck.dim]new session {session_id}[/ck.dim]")
    _chat_loop(root, settings, yes, test, session_id)


@app.command()
def sessions(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """List saved sessions for the workspace."""
    root = _workspace(workspace)
    items = list_sessions(root)
    if not items:
        console.print("[ck.dim]no saved sessions yet[/ck.dim]")
        return
    table = Table(box=None, pad_edge=False, show_header=True)
    table.add_column("#", style="ck.dim", justify="right")
    table.add_column("session", style="ck.accent")
    table.add_column("updated", style="ck.dim")
    table.add_column("task", overflow="ellipsis", max_width=44)
    table.add_column("msgs", justify="right", style="ck.dim")
    table.add_column("tokens", justify="right", style="ck.dim")
    current = current_session_id(root)
    for i, meta in enumerate(items, 1):
        marker = "*" if meta.session_id == current else " "
        table.add_row(
            str(i),
            f"{marker}{meta.session_id}",
            meta.updated_at.replace("T", " ")[:19],
            meta.prompt[:44] or "—",
            str(meta.nodes),
            f"{meta.token_input}/{meta.token_output}",
        )
    console.print(table)
    hint = "  codeking -r <n> 恢复指定会话 · codeking -r 交互选择 · codeking new 新会话 · * = 当前"
    console.print(f"[ck.faint]{hint}[/ck.faint]")


def _resolve_resume(root: Path, index: int | None) -> str | None:
    """Return the session_id to resume, or None to cancel."""
    items = list_sessions(root)
    if not items:
        console.print("[ck.dim]no saved sessions yet — starting fresh instead[/ck.dim]")
        return None
    if index is not None:
        if not 1 <= index <= len(items):
            console.print(f"[ck.err]invalid session index {index}[/ck.err]")
            return None
        return items[index - 1].session_id
    console.print(f"[ck.brand]{BRAND_MARK} resume session[/ck.brand]")
    for i, meta in enumerate(items, 1):
        console.print(
            f"  [ck.dim]{i}.[/ck.dim] {meta.session_id}  [ck.dim]{meta.updated_at[:19]}[/ck.dim]"
            f"  {meta.prompt[:40] or '—'}"  # noqa: E501
        )
    try:
        choice = console.input("[ck.accent]№ [/]").strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return None
    if not choice or not choice.isdigit() or not 1 <= int(choice) <= len(items):
        console.print("[ck.dim]cancelled[/ck.dim]")
        return None
    return items[int(choice) - 1].session_id


def _chat_loop(root: Path, settings, yes: bool, test: str | None, session_id: str) -> None:
    session_id = ensure_session(root, session_id)
    state = _state_from_session(root, session_id)
    while True:
        try:
            prompt = console.input("[ck.accent]❯ [/]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not prompt or prompt in {"/exit", "/quit"}:
            break
        if prompt == "/new":
            session_id = new_session_id(root)
            set_current_session_id(root, session_id)
            state = None
            console.print(f"[ck.dim]new session {session_id}[/ck.dim]")
            continue
        state = asyncio.run(
            _run_task(prompt, settings, auto_approve=yes, resume=state, test_command=test)
        )
        save_session(
            root,
            {
                "task_id": state.task_id,
                "prompt": state.task,
                "status": state.status.value,
                "role": state.role.value,
                "messages": state.messages,
                "snapshot": state.snapshot,
                "changed_files": state.changed_files,
                "plan": [{"title": i.title, "done": i.done} for i in state.plan],
                "test_results": state.test_results,
                "last_test_ok": state.last_test_ok,
                "iteration": state.iteration,
                "token_input": state.token_input,
                "token_output": state.token_output,
            },
            session_id=session_id,
        )


def _state_from_session(workspace: Path, session_id: str | None = None) -> AgentState | None:
    raw = load_session(workspace, session_id)
    if not raw:
        return None
    plan = [PlanItem(title=p["title"], done=p.get("done", False)) for p in raw.get("plan") or []]
    state = AgentState(
        task=str(raw.get("prompt") or ""),
        repository=str(workspace),
        task_id=str(raw.get("task_id") or ""),
        role=Role(raw.get("role") or "planner"),
        status=TaskStatus(raw.get("status") or "pending"),
        plan=plan,
        messages=list(raw.get("messages") or []),
        changed_files=list(raw.get("changed_files") or []),
        test_results=str(raw.get("test_results") or ""),
        iteration=int(raw.get("iteration") or 0),
        token_input=int(raw.get("token_input") or 0),
        token_output=int(raw.get("token_output") or 0),
        last_test_ok=raw.get("last_test_ok"),
        snapshot=dict(raw.get("snapshot") or {}),
    )
    if not state.task_id:
        return None
    return state


async def _run_task(
    prompt: str,
    settings,
    auto_approve: bool,
    resume: AgentState | None,
    test_command: str | None = None,
) -> AgentState:
    cancel = CancellationToken()
    runtime = AgentRuntime(settings, OpenAICompatProvider(settings), cancel=cancel)
    lines: list[Text] = []
    tick = [0]

    def render() -> Text:
        head = Text.assemble(
            (f"{BRAND_MARK} ", "ck.brand"),
            (spinner_label(tick[0]), "ck.dim"),
            ("\n", ""),
        )
        body = Text("\n").join(lines[-12:])
        return Text.assemble(head, body)

    async def on_event(event: AgentEvent) -> None:
        payload = event.payload
        if event.type == "tool_call":
            markup = print_run_event({"type": "tool_call", **payload})
            if markup:
                lines.append(Text.from_markup(markup))
        elif event.type == "terminal":
            markup = print_run_event({"type": "terminal", **payload})
            if markup:
                lines.append(Text.from_markup(markup))
        elif event.type == "approval_required":
            markup = print_run_event({"type": "approval_required", **payload})
            lines.append(Text.from_markup(markup))
        elif event.type == "error":
            msg = str(payload.get("message", ""))[:100]
            lines.append(Text.from_markup(f"[ck.err]⏺ 错误[/ck.err] [ck.faint]{msg}[/ck.faint]"))

    async def approve(tool: str, reason: str, arguments: dict) -> bool:
        return typer.confirm(f"Approve {tool} ({reason})? {arguments}", default=False)

    with Live(console=console, refresh_per_second=8) as live:

        async def wrapped(event: AgentEvent) -> None:
            await on_event(event)
            tick[0] += 1
            live.update(render())

        state = await runtime.run(
            prompt,
            settings.resolved_workspace(),
            on_event=wrapped,
            approve=None if auto_approve else approve,
            auto_approve=auto_approve,
            test_command=test_command,
            state=resume,
        )
    print_state(state)
    return state


@app.command()
def status(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Show the current task record."""
    record = load_current(_workspace(workspace))
    if record is None:
        console.print("[ck.dim]暂无任务记录[/ck.dim]")
        raise typer.Exit(0)
    console.print(f"[ck.brand]{BRAND_MARK} 当前任务[/ck.brand]")
    console.print(f"  [ck.dim]ID[/ck.dim]      {record.task_id}")
    console.print(f"  [ck.dim]任务[/ck.dim]    {record.prompt[:80]}")
    console.print(f"  [ck.dim]状态[/ck.dim]    {record.status}")
    console.print(f"  [ck.dim]文件[/ck.dim]    {len(record.changed_files)} 个变更")
    console.print(f"  [ck.dim]用量[/ck.dim]    {record.token_input} → {record.token_output} tokens")


@app.command()
def stop(
    task_id: str = typer.Argument(...),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Request cancellation for a running task."""
    request_cancel(_workspace(workspace), task_id)
    console.print(f"cancel requested for {task_id}")


@app.command()
def diff(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Show git diff in the workspace."""
    asyncio.run(_diff(_workspace(workspace)))


async def _diff(root: Path) -> None:
    sandbox = LocalProcessSandbox(root)
    result = await sandbox.run("git diff", timeout_sec=30)
    console.print(result.combined or "(no diff)")


@app.command()
def test(
    command: str = typer.Option("python -m pytest -q", "--command", "-c"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Run tests in the sandbox fallback/local process."""
    asyncio.run(_test(_workspace(workspace), command))


async def _test(root: Path, command: str) -> None:
    sandbox = LocalProcessSandbox(root)
    result = await sandbox.run(command, timeout_sec=120)
    console.print(result.combined or "(no output)")
    raise typer.Exit(result.exit_code)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Start FastAPI + WebSocket (CLI and Web share this Runtime API)."""
    uvicorn.run("coderking.api.app:app", host=host, port=port, reload=False)


@app.command()
def eval(
    eval_root: Path = typer.Option(Path("eval/tasks"), "--path"),
    report_dir: Path = typer.Option(Path("eval/reports"), "--report-dir"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Run the coding-agent evaluation suite and write reports."""
    settings = load_settings(workspace=_workspace(workspace), sandbox_mode="local")
    if not settings.openai_api_key:
        console.print("CODERKING_OPENAI_API_KEY is missing; copy .env.example to .env")
        raise typer.Exit(1)
    asyncio.run(_eval(eval_root, report_dir, settings))


async def _eval(eval_root: Path, report_dir: Path, settings) -> None:
    llm = OpenAICompatProvider(settings)
    results = await run_suite(eval_root, settings, llm)
    table = Table(title="CoderKing eval")
    table.add_column("task")
    table.add_column("cat")
    table.add_column("ok")
    table.add_column("tests")
    table.add_column("iters")
    for row in results:
        table.add_row(
            row.task_id,
            row.category,
            str(row.success),
            str(row.test_pass),
            str(row.iterations),
        )
    console.print(table)
    summary = summarize(results)
    console.print(summary)
    extra = {
        "llm": {
            "mode": "live",
            "model": settings.model,
            "base_url": settings.openai_base_url,
        },
        "sandbox_mode": settings.sandbox_mode,
    }
    json_path, md_path = write_reports(results, report_dir, stem="latest", extra=extra)
    write_reports(results, report_dir, stem="phase1-report", extra=extra)
    console.print(f"wrote {json_path} and {md_path}")
    if not results:
        discovered = discover_tasks(eval_root)
        console.print(f"discovered {len(discovered)} tasks")


@config_app.command("model")
def config_model(
    name: str | None = typer.Option(None, "--name", "--model"),
    base_url: str | None = typer.Option(None, "--base-url"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Save OpenAI-compatible model settings into .coderking/config.yaml (not the API key)."""
    root = _workspace(workspace)
    updates = {}
    if name:
        updates["model"] = name
    if base_url:
        updates["openai_base_url"] = base_url
    if updates:
        path = write_yaml_config(root, updates)
        console.print(f"wrote {path}")
    settings = load_settings(workspace=root)
    console.print(
        {
            "model": settings.model,
            "base_url": settings.openai_base_url,
            "disable_thinking": settings.disable_thinking,
            "api_key_set": bool(settings.openai_api_key),
        }
    )


def _print_state(state: AgentState) -> None:
    print_state(state)


def main() -> None:
    """Entry point: bare `coderking` / `codeking` drops straight into chat.

    Also maps claude-style shortcuts before Typer sees them:
      codeking          → continue the current session
      codeking -c       → same as bare (explicit continue)
      codeking -r       → interactive session picker
      codeking -r 2     → resume the 2nd session from `codeking sessions`
    """
    import sys

    argv = sys.argv[1:]
    if not argv:
        sys.argv = [sys.argv[0], "chat"]
    elif argv[0] in {"-r", "--resume"}:
        rest = argv[1:]
        rewritten = [sys.argv[0], "chat", "--resume"]
        if rest and rest[0].isdigit():
            rewritten += ["--resume-index", rest[0]]
            rest = rest[1:]
        sys.argv = rewritten + rest
    elif argv[0] in {"-c", "--continue"}:
        sys.argv = [sys.argv[0], "chat", *argv[1:]]
    app()


if __name__ == "__main__":
    main()
