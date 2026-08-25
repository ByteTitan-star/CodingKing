from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.live import Live
from rich.table import Table

from coderking import __version__
from coderking.config import config_yaml_path, load_settings, write_yaml_config
from coderking.evalkit.loader import discover_tasks
from coderking.evalkit.runner import run_suite, summarize, write_reports
from coderking.llm.openai_compat import OpenAICompatProvider
from coderking.registry import load_current, load_session, request_cancel, save_session
from coderking.runtime.cancel import CancellationToken
from coderking.runtime.events import AgentEvent
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import AgentState, PlanItem, Role, TaskStatus
from coderking.sandbox.local import LocalProcessSandbox

app = typer.Typer(no_args_is_help=True, add_completion=False, help="CoderKing coding agent CLI")
config_app = typer.Typer(no_args_is_help=True, help="Configure models and runtime")
app.add_typer(config_app, name="config")
console = Console()


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
    """Create .coderking/config.yaml in the workspace."""
    root = _workspace(workspace)
    (root / ".coderking" / "memory").mkdir(parents=True, exist_ok=True)
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
    console.print(f"initialized {root / '.coderking'}")


@app.command()
def run(
    prompt: str = typer.Argument(..., help="Natural language engineering task"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", help="Auto-approve dangerous tools"),
    commit: bool = typer.Option(False, "--commit", help="Allow git_commit"),
) -> None:
    """Run the agent against a repository (in-process Runtime, same as Web)."""
    settings = load_settings(workspace=_workspace(workspace), allow_commit=commit)
    asyncio.run(_run_task(prompt, settings, auto_approve=yes, resume=None))


@app.command()
def chat(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes"),
    commit: bool = typer.Option(False, "--commit"),
) -> None:
    """Interactive session that continues on the same workspace."""
    root = _workspace(workspace)
    settings = load_settings(workspace=root, allow_commit=commit)
    console.print("CoderKing chat. Empty line or /exit to quit.")
    state = _state_from_session(root)
    while True:
        try:
            prompt = console.input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not prompt or prompt in {"/exit", "/quit"}:
            break
        state = asyncio.run(_run_task(prompt, settings, auto_approve=yes, resume=state))
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
        )


def _state_from_session(workspace: Path) -> AgentState | None:
    raw = load_session(workspace)
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
) -> AgentState:
    cancel = CancellationToken()
    runtime = AgentRuntime(settings, OpenAICompatProvider(settings), cancel=cancel)
    lines: list[str] = []

    async def on_event(event: AgentEvent) -> None:
        payload = event.payload
        if event.type == "agent_status":
            lines.append(f"[status] {payload.get('role')} / {payload.get('status')}")
        elif event.type == "tool_call":
            lines.append(f"[tool] {payload.get('tool')} {payload.get('status')}")
        elif event.type == "terminal":
            lines.append(str(payload.get("text", ""))[:400])
        elif event.type == "done":
            lines.append(f"[done] ok={payload.get('ok')} {payload.get('summary')}")
        elif event.type == "error":
            lines.append(f"[error] {payload.get('message')}")

    async def approve(tool: str, reason: str, arguments: dict) -> bool:
        return typer.confirm(f"Approve {tool} ({reason})? {arguments}", default=False)

    with Live(console=console, refresh_per_second=8) as live:

        async def wrapped(event: AgentEvent) -> None:
            await on_event(event)
            live.update("\n".join(lines[-30:]))

        state = await runtime.run(
            prompt,
            settings.resolved_workspace(),
            on_event=wrapped,
            approve=None if auto_approve else approve,
            auto_approve=auto_approve,
            state=resume,
        )
    _print_state(state)
    return state


@app.command()
def status(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Show the current task record."""
    record = load_current(_workspace(workspace))
    if record is None:
        console.print("no current task")
        raise typer.Exit(0)
    console.print(
        {
            "Task ID": record.task_id,
            "Task": record.prompt,
            "Status": record.status,
            "Current Role": record.role,
            "Iteration": record.iteration,
            "Changed Files": record.changed_files,
            "Tests": record.test_results[:1000] or "(none)",
            "Token Usage": f"{record.token_input} / {record.token_output}",
        }
    )


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
    json_path, md_path = write_reports(
        results,
        report_dir,
        extra={"model": settings.model, "sandbox_mode": settings.sandbox_mode},
    )
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
    console.print(
        {
            "task_id": state.task_id,
            "status": state.status.value,
            "role": state.role.value,
            "iteration": state.iteration,
            "changed_files": state.changed_files,
        }
    )


if __name__ == "__main__":
    app()
