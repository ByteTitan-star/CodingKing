from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from coderking import __version__
from coderking.config import config_yaml_path, load_settings, write_yaml_config
from coderking.evalkit.loader import discover_tasks
from coderking.evalkit.runner import run_suite, summarize, write_reports
from coderking.llm.openai_compat import OpenAICompatProvider
from coderking.mcp.config import load_mcp_config
from coderking.mcp.host import McpHost
from coderking.registry import (
    current_session_id,
    ensure_session,
    list_sessions,
    load_current,
    load_session,
    load_session_run,
    load_task,
    new_session_id,
    query_task_index,
    rebuild_task_index,
    request_cancel,
    save_session,
    session_jsonl_path,
    set_current_session_id,
)
from coderking.runtime.cancel import CancellationToken
from coderking.runtime.checkpoints import CheckpointStore
from coderking.runtime.events import AgentEvent
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import (
    AgentState,
    PlanItem,
    Role,
    TaskStatus,
    ToolRecord,
    new_run_state,
)
from coderking.sandbox.local import LocalProcessSandbox
from coderking.tools.registry import ATOMIC_TOOL_NAMES
from coderking.ui.splash import play_splash
from coderking.ui.theme import (
    BRAND_MARK,
    THEME,
    console,
    print_banner,
    print_run_event,
    print_state,
    spinner_label,
)
from coderking_agent_core.types import AgentMessage
from coderking_coding_agent.context.budget import TokenBudget, estimate_messages_tokens
from coderking_coding_agent.context.skills import SkillRegistry, parse_skill_file
from coderking_coding_agent.context.transform import ContextCompressor
from coderking_coding_agent.runtime.atomic_l1 import (
    agent_message_from_dict,
    agent_message_to_dict,
)
from coderking_coding_agent.session import SessionNode, SessionRepo
from coderking_coding_agent.tools.dynamic import scan_tool_manifests

app = typer.Typer(no_args_is_help=True, add_completion=False, help="CoderKing coding agent CLI")
config_app = typer.Typer(no_args_is_help=True, help="Configure models and runtime")
skills_app = typer.Typer(no_args_is_help=False, help="Inspect and validate available skills")
tools_app = typer.Typer(no_args_is_help=False, help="Inspect optional dynamic tools")
mcp_app = typer.Typer(no_args_is_help=False, help="Inspect and validate MCP servers")
session_app = typer.Typer(no_args_is_help=True, help="Inspect and branch session trees")
checkpoint_app = typer.Typer(no_args_is_help=True, help="Inspect and restore tool checkpoints")
app.add_typer(config_app, name="config")
app.add_typer(skills_app, name="skills")
app.add_typer(tools_app, name="tools")
app.add_typer(mcp_app, name="mcp")
app.add_typer(session_app, name="session")
app.add_typer(checkpoint_app, name="checkpoint")


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
    (root / ".coderking" / "skills").mkdir(parents=True, exist_ok=True)
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


def _available_skills(root: Path) -> SkillRegistry:
    return SkillRegistry(root, include_cursor=True, include_global=True)


def _print_skills(root: Path) -> None:
    registry = _available_skills(root)
    manifests = registry.manifests()
    if not manifests:
        console.print("[ck.dim]no skills found[/ck.dim]")
        console.print("[ck.faint]add <workspace>/.coderking/skills/<name>/SKILL.md[/ck.faint]")
        return
    table = Table(box=None, pad_edge=False, show_header=True)
    table.add_column("skill", style="ck.accent")
    table.add_column("source", style="ck.dim")
    table.add_column("description", overflow="ellipsis", max_width=60)
    for manifest in manifests:
        table.add_row(manifest.name, manifest.source, manifest.description)
    console.print(table)
    if registry.diagnostics():
        console.print(
            f"[ck.err]{len(registry.diagnostics())} invalid/duplicate skill definition(s); "
            "run `codeking skills check`[/ck.err]"
        )


@skills_app.callback(invoke_without_command=True)
def skills_root(ctx: typer.Context) -> None:
    """List skills when no skills subcommand is provided."""
    if ctx.invoked_subcommand is None:
        _print_skills(Path.cwd().resolve())


@skills_app.command("list")
def skills_list(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """List workspace, global, and Cursor-compatible skills."""
    _print_skills(_workspace(workspace))


@skills_app.command("show")
def skills_show(
    name: str = typer.Argument(..., help="Skill name"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Show one skill definition and its source path."""
    registry = _available_skills(_workspace(workspace))
    manifest = registry.get(name)
    if manifest is None:
        console.print(f"[ck.err]unknown skill: {name}[/ck.err]")
        raise typer.Exit(1)
    _, body = parse_skill_file(manifest.path.read_text(encoding="utf-8"))
    console.print(f"[ck.brand]{manifest.name}[/ck.brand] [ck.dim]{manifest.path}[/ck.dim]")
    console.print(Markdown(body))


@skills_app.command("check")
def skills_check(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Validate all discovered skill manifests."""
    registry = _available_skills(_workspace(workspace))
    diagnostics = registry.diagnostics()
    if not diagnostics:
        console.print(f"[ck.ok]{len(registry.manifests())} skill(s) valid[/ck.ok]")
        return
    for diagnostic in diagnostics:
        console.print(f"[ck.err]• {diagnostic}[/ck.err]")
    raise typer.Exit(1)


def _print_tools(root: Path) -> None:
    settings = load_settings(workspace=root)
    manifests, errors = scan_tool_manifests(root)
    table = Table(box=None, pad_edge=False, show_header=True)
    table.add_column("tool", style="ck.accent")
    table.add_column("source", style="ck.dim")
    table.add_column("runtime")
    for name in sorted(ATOMIC_TOOL_NAMES):
        table.add_row(name, "atomic", "enabled")
    for manifest in manifests:
        status = "enabled" if settings.dynamic_tools_enabled else "disabled"
        table.add_row(manifest.name, "workspace", status)
    console.print(table)
    if errors:
        console.print(
            f"[ck.err]{len(errors)} invalid dynamic tool definition(s); "
            "run `codeking tools check`[/ck.err]"
        )


@tools_app.callback(invoke_without_command=True)
def tools_root(ctx: typer.Context) -> None:
    """List tools when no tools subcommand is provided."""
    if ctx.invoked_subcommand is None:
        _print_tools(Path.cwd().resolve())


@tools_app.command("list")
def tools_list(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """List atomic and workspace dynamic tools."""
    _print_tools(_workspace(workspace))


@tools_app.command("check")
def tools_check(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Validate workspace dynamic tool manifests and name conflicts."""
    manifests, errors = scan_tool_manifests(_workspace(workspace))
    diagnostics = dict(errors)
    for manifest in manifests:
        if manifest.name in ATOMIC_TOOL_NAMES:
            diagnostics[manifest.name] = "name conflicts with an atomic tool"
    if not diagnostics:
        console.print(f"[ck.ok]{len(manifests)} dynamic tool(s) valid[/ck.ok]")
        return
    for name, message in sorted(diagnostics.items()):
        console.print(f"[ck.err]• {name}: {message}[/ck.err]")
    raise typer.Exit(1)


def _print_mcp_servers(root: Path) -> None:
    try:
        config = load_mcp_config(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        console.print(f"[ck.err]{exc}[/ck.err]")
        raise typer.Exit(1) from exc
    settings = load_settings(workspace=root)
    if not config.servers:
        console.print("[ck.dim]no MCP servers configured[/ck.dim]")
        return
    allowed = set(config.allowlist)
    table = Table(box=None, pad_edge=False, show_header=True)
    table.add_column("server", style="ck.accent")
    table.add_column("configured")
    table.add_column("allowlisted")
    table.add_column("runtime")
    for server in config.servers:
        table.add_row(
            server.name,
            "enabled" if server.enabled else "disabled",
            "yes" if server.name in allowed else "no",
            "enabled" if settings.mcp_enabled else "disabled",
        )
    console.print(table)


@mcp_app.callback(invoke_without_command=True)
def mcp_root(ctx: typer.Context) -> None:
    """List MCP servers when no MCP subcommand is provided."""
    if ctx.invoked_subcommand is None:
        _print_mcp_servers(Path.cwd().resolve())


@mcp_app.command("list")
def mcp_list(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """List configured MCP servers without starting them."""
    _print_mcp_servers(_workspace(workspace))


@mcp_app.command("check")
def mcp_check(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
    timeout: float = typer.Option(30.0, "--timeout", min=1, max=300),
) -> None:
    """Connect to allowlisted MCP servers, discover tools, then close them."""
    root = _workspace(workspace)

    async def check() -> list[str]:
        host = await McpHost.connect(root, timeout_sec=timeout)
        try:
            return sorted(host.names())
        finally:
            await host.close()

    try:
        names = asyncio.run(check())
    except Exception as exc:
        console.print(f"[ck.err]MCP check failed: {exc}[/ck.err]")
        raise typer.Exit(1) from exc
    if not names:
        console.print("[ck.dim]no allowlisted MCP servers/tools[/ck.dim]")
        return
    console.print(f"[ck.ok]{len(names)} MCP tool(s) available[/ck.ok]")
    for name in names:
        console.print(f"  {name}")


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
    dynamic_tools: bool = typer.Option(False, "--dynamic-tools"),
    mcp: bool = typer.Option(False, "--mcp"),
) -> None:
    """Interactive Textual TUI (chat / tools / terminal panels)."""
    from coderking.tui_runner import run_interactive_tui

    root = _workspace(workspace)
    settings = load_settings(
        workspace=root,
        allow_commit=commit,
        dynamic_tools_enabled=True if dynamic_tools else None,
        mcp_enabled=True if mcp else None,
    )
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
    skill: list[str] = typer.Option([], "--skill", help="Explicit skill to load (repeatable)"),
    dynamic_tools: bool = typer.Option(False, "--dynamic-tools"),
    mcp: bool = typer.Option(False, "--mcp"),
) -> None:
    """Run the agent against a repository (in-process Runtime, same as Web)."""
    settings = load_settings(
        workspace=_workspace(workspace),
        allow_commit=commit,
        dynamic_tools_enabled=True if dynamic_tools else None,
        mcp_enabled=True if mcp else None,
    )
    print_banner(
        workspace=settings.resolved_workspace(),
        model=settings.model,
        sandbox=settings.sandbox_mode,
        interactive=False,
    )
    asyncio.run(
        _run_task(
            prompt,
            settings,
            auto_approve=yes,
            resume=None,
            test_command=test,
            skill_names=skill,
        )
    )


@app.command()
def retry(
    task_id: str = typer.Argument(..., help="Failed or interrupted task id"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
    prompt: str | None = typer.Option(None, "--prompt", help="Override the original prompt"),
    yes: bool = typer.Option(False, "--yes", help="Auto-approve dangerous tools"),
    commit: bool = typer.Option(False, "--commit", help="Allow git_commit"),
    test: str | None = typer.Option(None, "--test", help="Preferred verification command"),
    skill: list[str] = typer.Option([], "--skill", help="Explicit skill to load"),
    dynamic_tools: bool = typer.Option(False, "--dynamic-tools"),
    mcp: bool = typer.Option(False, "--mcp"),
) -> None:
    """Retry a failed/interrupted run as a new child run."""
    root = _workspace(workspace)
    try:
        record = load_task(root, task_id)
    except ValueError as exc:
        console.print(f"[ck.err]{exc}[/ck.err]")
        raise typer.Exit(1) from exc
    if record is None:
        console.print("[ck.err]task not found[/ck.err]")
        raise typer.Exit(1)
    if record.status not in {"failed", "interrupted"}:
        console.print(
            f"[ck.err]task {record.task_id} is {record.status}; "
            "only failed or interrupted tasks can be retried[/ck.err]"
        )
        raise typer.Exit(1)

    previous: AgentState | None = None
    if record.session_id:
        raw = load_session_run(root, record.session_id, record.task_id)
        previous = _state_from_session_payload(root, raw, session_id=record.session_id)
    if previous is None:
        previous = AgentState(
            task=record.prompt,
            repository=str(root),
            task_id=record.task_id,
            session_id=record.session_id,
            status=TaskStatus(record.status),
        )

    settings = load_settings(
        workspace=root,
        allow_commit=commit,
        dynamic_tools_enabled=True if dynamic_tools else None,
        mcp_enabled=True if mcp else None,
    )
    retry_prompt = prompt or record.prompt
    print_banner(
        workspace=root,
        model=settings.model,
        sandbox=settings.sandbox_mode,
        interactive=False,
    )
    state = asyncio.run(
        _run_task(
            retry_prompt,
            settings,
            auto_approve=yes,
            resume=previous,
            test_command=test,
            skill_names=skill,
            session_id=record.session_id,
        )
    )
    if record.session_id:
        _save_chat_state(root, record.session_id, state)


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
    skill: list[str] = typer.Option([], "--skill", help="Explicit skill to load (repeatable)"),
    dynamic_tools: bool = typer.Option(False, "--dynamic-tools"),
    mcp: bool = typer.Option(False, "--mcp"),
) -> None:
    """Interactive session that continues on the same workspace."""
    root = _workspace(workspace)
    settings = load_settings(
        workspace=root,
        allow_commit=commit,
        dynamic_tools_enabled=True if dynamic_tools else None,
        mcp_enabled=True if mcp else None,
    )
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
    _chat_loop(root, settings, yes, test, session_id, skill)


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
    skill: list[str] = typer.Option([], "--skill", help="Explicit skill to load (repeatable)"),
    dynamic_tools: bool = typer.Option(False, "--dynamic-tools"),
    mcp: bool = typer.Option(False, "--mcp"),
) -> None:
    """Start a fresh session on the workspace (keeps old ones)."""
    root = _workspace(workspace)
    settings = load_settings(
        workspace=root,
        allow_commit=commit,
        dynamic_tools_enabled=True if dynamic_tools else None,
        mcp_enabled=True if mcp else None,
    )
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
    _chat_loop(root, settings, yes, test, session_id, skill)


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


def _session_node_summary(node: SessionNode) -> str:
    message = node.payload.get("message")
    if isinstance(message, dict):
        return str(message.get("content") or message.get("role") or "")[:70]
    snapshot = node.payload.get("session_snapshot")
    if isinstance(snapshot, dict):
        return str(snapshot.get("prompt") or snapshot.get("status") or "")[:70]
    if node.kind == "compression":
        return f"replacement messages: {len(node.payload.get('messages') or [])}"
    return str(node.payload.get("label") or "")[:70]


@session_app.command("tree")
def session_tree(
    session_id: str | None = typer.Argument(None, help="Session id; defaults to current"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Show every node and which branch currently leads to HEAD."""
    root = _workspace(workspace)
    sid = session_id or current_session_id(root)
    try:
        if not session_jsonl_path(root, sid).is_file():
            raise ValueError(f"session {sid!r} does not exist")
        repo = SessionRepo(root, session_id=sid)
        active = {node.id for node in repo.walk_to_head()}
    except (OSError, ValueError) as exc:
        console.print(f"[ck.err]{exc}[/ck.err]")
        raise typer.Exit(1) from exc
    table = Table(box=None, pad_edge=False, show_header=True)
    table.add_column("active")
    table.add_column("node", style="ck.accent")
    table.add_column("parent", style="ck.dim")
    table.add_column("kind")
    table.add_column("summary", overflow="ellipsis", max_width=70)
    for node in repo.nodes():
        table.add_row(
            "*" if node.id in active else "",
            node.id,
            node.parent_id or "—",
            node.kind,
            _session_node_summary(node),
        )
    console.print(table)
    console.print(f"[ck.dim]session={sid} head={repo.head_id}[/ck.dim]")


@session_app.command("branch")
def session_branch(
    node_id: str = typer.Argument(..., help="Existing node id to make HEAD"),
    session_id: str | None = typer.Option(None, "--session", help="Defaults to current"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Move a session's HEAD to a node without deleting either branch."""
    root = _workspace(workspace)
    sid = session_id or current_session_id(root)
    try:
        if not session_jsonl_path(root, sid).is_file():
            raise ValueError(f"session {sid!r} does not exist")
        repo = SessionRepo(root, session_id=sid)
        repo.branch_to(node_id)
        set_current_session_id(root, sid)
    except (KeyError, OSError, ValueError) as exc:
        console.print(f"[ck.err]{exc}[/ck.err]")
        raise typer.Exit(1) from exc
    console.print(f"[ck.ok]session {sid} now points to {node_id}[/ck.ok]")


@session_app.command("fork")
def session_fork(
    source: str | None = typer.Option(None, "--from", help="Source; defaults to current"),
    name: str | None = typer.Option(None, "--name", help="New session id"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Copy the active branch into a new independent session and switch to it."""
    root = _workspace(workspace)
    source_id = source or current_session_id(root)
    target_id = name or new_session_id(root)
    try:
        state = load_session(root, source_id)
        if not state:
            raise ValueError(f"session {source_id!r} has no saved state")
        target_path = session_jsonl_path(root, target_id)
        if target_path.exists():
            raise ValueError(f"session {target_id!r} already exists")
        state["session_id"] = target_id
        save_session(root, state, session_id=target_id)
        set_current_session_id(root, target_id)
    except (OSError, ValueError) as exc:
        console.print(f"[ck.err]{exc}[/ck.err]")
        raise typer.Exit(1) from exc
    console.print(f"[ck.ok]forked {source_id} → {target_id}[/ck.ok]")


def _checkpoint_task(root: Path, task_id: str | None):
    record = load_task(root, task_id) if task_id else load_current(root)
    if record is None:
        raise ValueError("task not found")
    return record


@checkpoint_app.command("list")
def checkpoint_list(
    task_id: str | None = typer.Argument(None, help="Task id; defaults to current"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """List persisted file checkpoints for a task."""
    root = _workspace(workspace)
    try:
        record = _checkpoint_task(root, task_id)
        items = CheckpointStore(root, root, record.task_id).list()
    except (OSError, ValueError) as exc:
        console.print(f"[ck.err]{exc}[/ck.err]")
        raise typer.Exit(1) from exc
    if not items:
        console.print("[ck.dim]no checkpoints[/ck.dim]")
        return
    table = Table(box=None, pad_edge=False, show_header=True)
    table.add_column("checkpoint", style="ck.accent")
    table.add_column("status")
    table.add_column("turn", style="ck.dim")
    table.add_column("tool")
    table.add_column("path")
    for item in items:
        table.add_row(
            str(item.get("checkpoint_id") or "?"),
            str(item.get("status") or "?"),
            str(item.get("turn_id") or "—"),
            str(item.get("tool") or "?"),
            str(item.get("path") or "?"),
        )
    console.print(table)


@checkpoint_app.command("rollback")
def checkpoint_rollback(
    checkpoint_id: str = typer.Argument(..., help="Checkpoint id"),
    task_id: str | None = typer.Option(None, "--task", help="Task id; defaults to current"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation"),
) -> None:
    """Restore the file state captured before one mutating tool call."""
    root = _workspace(workspace)
    try:
        record = _checkpoint_task(root, task_id)
        if record.status in {"pending", "running", "cancelling", "waiting_approval"}:
            raise ValueError(f"cannot rollback checkpoint while task is {record.status}")
        store = CheckpointStore(root, root, record.task_id)
        item = store.load(checkpoint_id)
        path = str(item.get("path") or "?")
        if not yes and not typer.confirm(f"Restore {path} from {checkpoint_id}?", default=False):
            console.print("[ck.dim]cancelled[/ck.dim]")
            return
        restored = store.restore(checkpoint_id)
    except (KeyError, OSError, ValueError) as exc:
        console.print(f"[ck.err]{exc}[/ck.err]")
        raise typer.Exit(1) from exc
    console.print(f"[ck.ok]restored {restored.get('path')} from {checkpoint_id}[/ck.ok]")


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


def _read_input() -> str:
    """One prompt line: slash-completion REPL on a TTY, plain input otherwise."""
    if sys.stdin.isatty():
        try:
            from coderking.ui.repl_input import prompt as repl_prompt

            return repl_prompt()
        except Exception:
            pass  # prompt_toolkit unavailable or terminal unsupported
    return console.input("[ck.accent]❯ [/]").strip()


def _chat_loop(
    root: Path,
    settings,
    yes: bool,
    test: str | None,
    session_id: str,
    skill_names: Sequence[str] = (),
) -> None:
    session_id = ensure_session(root, session_id)
    state = _state_from_session(root, session_id)
    pending_skills = list(skill_names)
    while True:
        try:
            prompt = _read_input()
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
        if prompt == "/trace":
            _print_tool_trace(state)
            continue
        if prompt == "/skills":
            _print_skills(root)
            continue
        if prompt == "/context":
            _print_context_status(state, settings)
            continue
        if prompt == "/reload":
            _print_resource_summary(root, settings)
            continue
        if prompt.startswith("/compact"):
            if state is None:
                console.print("[ck.dim]current session has no context to compact[/ck.dim]")
                continue
            _compact_state(state, settings)
            _save_chat_state(root, session_id, state)
            continue
        selected, rewritten = _parse_skill_command(prompt)
        if selected is not None:
            registry = _available_skills(root)
            if registry.get(selected) is None:
                console.print(f"[ck.err]unknown skill: {selected}[/ck.err]")
                continue
            if not rewritten:
                if selected not in pending_skills:
                    pending_skills.append(selected)
                console.print(f"[ck.dim]skill {selected} will load with the next prompt[/ck.dim]")
                continue
            prompt = rewritten
            if selected not in pending_skills:
                pending_skills.append(selected)
        state = asyncio.run(
            _run_task(
                prompt,
                settings,
                auto_approve=yes,
                resume=state,
                test_command=test,
                skill_names=pending_skills,
                session_id=session_id,
            )
        )
        _save_chat_state(root, session_id, state)


def _parse_skill_command(prompt: str) -> tuple[str | None, str]:
    if prompt.startswith("/skill:"):
        command, _, rest = prompt.partition(" ")
        return command.removeprefix("/skill:").strip() or None, rest.strip()
    if prompt.startswith("/skill "):
        parts = prompt.split(maxsplit=2)
        return parts[1].strip() or None, parts[2].strip() if len(parts) == 3 else ""
    return None, prompt


def _print_resource_summary(root: Path, settings) -> None:
    registry = _available_skills(root)
    dynamic, dynamic_errors = scan_tool_manifests(root)
    try:
        mcp_servers = load_mcp_config(root).selected()
        mcp_error = None
    except Exception as exc:
        mcp_servers = []
        mcp_error = str(exc)
    console.print("[ck.ok]resources refreshed for the next run[/ck.ok]")
    console.print(f"  skills        {len(registry.manifests())}")
    console.print(
        f"  dynamic tools {len(dynamic)} "
        f"({'enabled' if settings.dynamic_tools_enabled else 'disabled'})"
    )
    console.print(
        f"  MCP servers   {len(mcp_servers)} ({'enabled' if settings.mcp_enabled else 'disabled'})"
    )
    diagnostic_count = len(registry.diagnostics()) + len(dynamic_errors) + int(bool(mcp_error))
    if diagnostic_count:
        console.print(f"[ck.err]{diagnostic_count} resource diagnostic(s)[/ck.err]")


def _save_chat_state(root: Path, session_id: str, state: AgentState) -> None:
    save_session(
        root,
        {
            "task_id": state.task_id,
            "parent_run_id": state.parent_run_id,
            "session_id": state.session_id,
            "turn_id": state.turn_id,
            "prompt": state.task,
            "status": state.status.value,
            "role": state.role.value,
            "messages": state.messages,
            "changed_files": state.changed_files,
            "plan": [{"title": item.title, "done": item.done} for item in state.plan],
            "test_results": state.test_results,
            "last_test_ok": state.last_test_ok,
            "errors": state.errors,
            "iteration": state.iteration,
            "token_input": state.token_input,
            "token_output": state.token_output,
            "context_tokens_estimated": state.context_tokens_estimated,
            "compression_count": state.compression_count,
            "micro_compaction_count": state.micro_compaction_count,
            "checkpoint_count": state.checkpoint_count,
            "latest_checkpoint_id": state.latest_checkpoint_id,
            "event_cursor": state.event_cursor,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "finished_at": state.finished_at,
            "pid": state.pid,
            "tool_history": [
                {
                    "name": record.name,
                    "arguments": record.arguments,
                    "output": record.output,
                    "ok": record.ok,
                    "ts": record.ts,
                }
                for record in state.tool_history
            ],
        },
        session_id=session_id,
    )


def _context_budget(settings) -> TokenBudget:
    return TokenBudget(
        context_window=settings.context_window,
        reserve_completion=settings.compression_reserve_tokens,
        compress_threshold=settings.compression_threshold,
    )


def _state_context_messages(state: AgentState) -> list[AgentMessage]:
    return [
        agent_message_from_dict(message)
        for index, message in enumerate(state.messages)
        if not (index == 0 and message.get("role") == "system")
    ]


def _print_context_status(state: AgentState | None, settings) -> None:
    messages = _state_context_messages(state) if state is not None else []
    estimated = estimate_messages_tokens(messages)
    budget = _context_budget(settings)
    console.print(f"[ck.brand]{BRAND_MARK} context[/ck.brand]")
    console.print(f"  estimated  {estimated} tokens")
    console.print(f"  threshold  {budget.max_prompt_tokens} tokens")
    console.print(f"  compressed {state.compression_count if state else 0} time(s)")
    console.print(f"  micro      {state.micro_compaction_count if state else 0} time(s)")


def _compact_state(state: AgentState, settings) -> None:
    messages = _state_context_messages(state)
    before = estimate_messages_tokens(messages)
    compressor = ContextCompressor(
        budget=_context_budget(settings),
        keep_recent_messages=settings.compression_keep_recent_messages,
    )
    compressed = asyncio.run(compressor.transform(messages, force=True))
    after = estimate_messages_tokens(compressed)
    if after >= before:
        console.print("[ck.dim]context is already too short to compact safely[/ck.dim]")
        return
    primary = (
        dict(state.messages[0])
        if state.messages and state.messages[0].get("role") == "system"
        else {"role": "system", "content": ""}
    )
    state.messages = [primary, *[agent_message_to_dict(message) for message in compressed]]
    state.context_tokens_estimated = after
    state.compression_count += 1
    console.print(f"[ck.ok]context compacted: {before} → {after} estimated tokens[/ck.ok]")


def _state_from_session(workspace: Path, session_id: str | None = None) -> AgentState | None:
    raw = load_session(workspace, session_id)
    return _state_from_session_payload(workspace, raw, session_id=session_id)


def _state_from_session_payload(
    workspace: Path,
    raw: dict,
    *,
    session_id: str | None = None,
) -> AgentState | None:
    if not raw:
        return None
    plan = [PlanItem(title=p["title"], done=p.get("done", False)) for p in raw.get("plan") or []]
    tool_history = [
        ToolRecord(
            name=str(t.get("name") or "?"),
            arguments=dict(t.get("arguments") or {}),
            output=str(t.get("output") or ""),
            ok=bool(t.get("ok")),
            ts=str(t.get("ts") or ""),
        )
        for t in raw.get("tool_history") or []
        if isinstance(t, dict)
    ]
    loaded_at = datetime.now(UTC).isoformat()
    state = AgentState(
        task=str(raw.get("prompt") or ""),
        repository=str(workspace),
        task_id=str(raw.get("task_id") or ""),
        parent_run_id=str(raw.get("parent_run_id") or "") or None,
        session_id=(
            str(raw.get("session_id") or "") or session_id or current_session_id(workspace)
        ),
        turn_id=str(raw.get("turn_id") or "") or None,
        role=Role(raw.get("role") or "planner"),
        status=TaskStatus(raw.get("status") or "pending"),
        plan=plan,
        messages=list(raw.get("messages") or []),
        changed_files=list(raw.get("changed_files") or []),
        test_results=str(raw.get("test_results") or ""),
        errors=list(raw.get("errors") or []),
        iteration=int(raw.get("iteration") or 0),
        token_input=int(raw.get("token_input") or 0),
        token_output=int(raw.get("token_output") or 0),
        context_tokens_estimated=int(raw.get("context_tokens_estimated") or 0),
        compression_count=int(raw.get("compression_count") or 0),
        micro_compaction_count=int(raw.get("micro_compaction_count") or 0),
        checkpoint_count=int(raw.get("checkpoint_count") or 0),
        latest_checkpoint_id=str(raw.get("latest_checkpoint_id") or "") or None,
        event_cursor=int(raw.get("event_cursor") or 0),
        last_test_ok=raw.get("last_test_ok"),
        snapshot=dict(raw.get("snapshot") or {}),
        tool_history=tool_history,
        created_at=str(raw.get("created_at") or "") or loaded_at,
        updated_at=str(raw.get("updated_at") or "") or loaded_at,
        finished_at=str(raw.get("finished_at") or "") or None,
        pid=int(raw.get("pid") or 0),
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
    skill_names: Sequence[str] = (),
    session_id: str | None = None,
) -> AgentState:
    cancel = CancellationToken()
    runtime = AgentRuntime(settings, OpenAICompatProvider(settings), cancel=cancel)
    lines: list[Text] = []
    stream: list[str] = []  # content deltas of the current assistant turn
    tick = [0]

    def render() -> Text:
        # Compact Claude-Code-style status: spinner + the current action only.
        # The full trace stays available via /trace after the run.
        head = Text.assemble(
            (f"{BRAND_MARK} ", "ck.brand"),
            (spinner_label(tick[0]), "ck.dim"),
        )
        if lines:
            head.append(Text("\n"))
            head.append(lines[-1])
        if stream:
            tail = "\n".join("".join(stream).splitlines()[-8:])
            head.append(Text("\n"))
            head.append(Text(tail, style="ck.dim"))
        return head

    async def on_event(event: AgentEvent) -> None:
        payload = event.payload
        if event.type == "content_delta":
            stream.append(str(payload.get("text") or ""))
            return
        if event.type == "tool_call":
            stream.clear()  # the model switched from writing to acting
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
        elif event.type in {"subagent_start", "subagent_end", "plan_update"}:
            markup = print_run_event({"type": event.type, **payload})
            if markup:
                lines.append(Text.from_markup(markup))
        elif event.type == "error":
            msg = str(payload.get("message", ""))[:100]
            lines.append(Text.from_markup(f"[ck.err]⏺ 错误[/ck.err] [ck.faint]{msg}[/ck.faint]"))
        elif event.type == "context_compressed":
            before = int(payload.get("before_tokens") or 0)
            after = int(payload.get("after_tokens") or 0)
            lines.append(Text.from_markup(f"[ck.dim]⏺ context {before} → {after} tokens[/ck.dim]"))
        elif event.type == "context_micro_compacted":
            before = int(payload.get("before_tokens") or 0)
            after = int(payload.get("after_tokens") or 0)
            count = int(payload.get("tool_results_compacted") or 0)
            lines.append(
                Text.from_markup(
                    f"[ck.dim]⏺ context micro {before} → {after} tokens "
                    f"({count} tool results)[/ck.dim]"
                )
            )
        elif event.type == "resource_diagnostic":
            message = str(payload.get("message") or "resource loading issue")[:160]
            lines.append(Text.from_markup(f"[ck.warn]⚠ {message}[/ck.warn]"))
        elif event.type == "checkpoint":
            markup = print_run_event({"type": "checkpoint", **payload})
            if markup:
                lines.append(Text.from_markup(markup))
        elif event.type == "done":
            stream.clear()  # final reply is printed as Markdown below the Live

    async def approve(tool: str, reason: str, arguments: dict) -> bool:
        return typer.confirm(f"Approve {tool} ({reason})? {arguments}", default=False)

    with Live(console=console, refresh_per_second=20) as live:

        async def wrapped(event: AgentEvent) -> None:
            await on_event(event)
            tick[0] += 1
            live.update(render())

        run_state = _prepare_run_state(
            prompt,
            settings.resolved_workspace(),
            resume,
            session_id=session_id,
        )
        state = await runtime.run(
            prompt,
            settings.resolved_workspace(),
            on_event=wrapped,
            approve=None if auto_approve else approve,
            auto_approve=auto_approve,
            test_command=test_command,
            state=run_state,
            skill_names=skill_names,
        )
    collapsed = _summarize_tools(state.tool_history)
    if collapsed:
        console.print(f"[ck.faint]{collapsed}[/ck.faint]")
    reply = _last_assistant_text(state.messages)
    if reply:
        console.print()
        # Markdown renderer: formats headings/lists/code blocks properly and
        # never interprets model output as rich markup. Capped at a readable
        # width so wide terminals don't stretch paragraphs edge to edge.
        reply_console = Console(theme=THEME, width=min(console.width, 100))
        reply_console.print(Markdown(reply))
        console.print()
    print_state(state)
    return state


def _prepare_run_state(
    prompt: str,
    workspace: Path,
    previous: AgentState | None,
    *,
    session_id: str | None,
) -> AgentState:
    """Create a distinct task/run while carrying only session-level context."""
    return new_run_state(
        prompt,
        str(workspace),
        previous=previous,
        session_id=session_id,
    )


def _summarize_tools(tool_history: list) -> str:
    """One collapsed line for the whole run's tool activity."""
    if not tool_history:
        return ""
    counts: dict[str, int] = {}
    for record in tool_history:
        counts[record.name] = counts.get(record.name, 0) + 1
    parts = [name if n == 1 else f"{name} ×{n}" for name, n in counts.items()]
    return f"⏺ 工具 ×{len(tool_history)}：{' · '.join(parts)}（/trace 展开）"


def _print_tool_trace(state) -> None:
    """Expand the last run's tool trace (/trace command)."""
    history = getattr(state, "tool_history", None) or []
    if not history:
        console.print("[ck.dim]当前会话还没有工具调用记录[/ck.dim]")
        return
    console.print(f"[ck.brand]{BRAND_MARK} 工具轨迹[/ck.brand]（最近 {len(history)} 次）")
    for record in history:
        mark = "[ck.ok]✓[/ck.ok]" if record.ok else "[ck.err]✗[/ck.err]"
        args = json.dumps(record.arguments, ensure_ascii=False)[:80]
        console.print(f"  ⏺ {record.name} {args} {mark}")
        output = (record.output or "").strip()
        if output:
            for line in output.splitlines()[:3]:
                console.print(f"      [ck.faint]{line[:88]}[/ck.faint]")


def _last_assistant_text(messages: list[dict]) -> str:
    """Final assistant reply of a run — the content users actually want to see."""
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


@app.command()
def status(
    task_id: str | None = typer.Argument(None, help="Task id; defaults to current"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Show the current task record or a persisted task by id."""
    root = _workspace(workspace)
    try:
        record = load_task(root, task_id) if task_id else load_current(root)
    except ValueError as exc:
        console.print(f"[ck.err]{exc}[/ck.err]")
        raise typer.Exit(1) from exc
    if record is None:
        console.print("[ck.err]task not found[/ck.err]")
        raise typer.Exit(1 if task_id else 0)
    console.print(f"[ck.brand]{BRAND_MARK} task[/ck.brand]")
    console.print(f"  [ck.dim]ID[/ck.dim]      {record.task_id}")
    console.print(f"  [ck.dim]任务[/ck.dim]    {record.prompt[:80]}")
    console.print(f"  [ck.dim]状态[/ck.dim]    {record.status}")
    if record.session_id:
        console.print(f"  [ck.dim]会话[/ck.dim]    {record.session_id}")
    console.print(f"  [ck.dim]文件[/ck.dim]    {len(record.changed_files)} 个变更")
    console.print(f"  [ck.dim]用量[/ck.dim]    {record.token_input} → {record.token_output} tokens")
    console.print(
        f"  [ck.dim]上下文[/ck.dim]  {record.context_tokens_estimated} tokens · "
        f"压缩 {record.compression_count} 次 · 微压缩 {record.micro_compaction_count} 次"
    )
    if record.checkpoint_count:
        console.print(
            f"  [ck.dim]检查点[/ck.dim]  {record.checkpoint_count} 个 · "
            f"最新 {record.latest_checkpoint_id or '—'}"
        )


@app.command()
def tasks(
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
    status: str | None = typer.Option(None, "--status", help="Filter by exact task status"),
    limit: int = typer.Option(100, "--limit", min=1, max=10_000),
    rebuild_index: bool = typer.Option(
        False,
        "--rebuild-index",
        help="Rebuild state.db from portable JSON records before listing",
    ),
) -> None:
    """List persisted tasks through the derived SQLite index."""
    root = _workspace(workspace)
    if rebuild_index:
        rebuilt = rebuild_task_index(root)
        console.print(f"[ck.dim]rebuilt task index from {rebuilt} record(s)[/ck.dim]")
    records = query_task_index(root, status=status, limit=limit)
    if not records:
        console.print("[ck.dim]no task records[/ck.dim]")
        return
    table = Table(box=None, pad_edge=False, show_header=True)
    table.add_column("task", style="ck.accent")
    table.add_column("status")
    table.add_column("turns", justify="right", style="ck.dim")
    table.add_column("prompt", overflow="ellipsis", max_width=60)
    for record in records:
        table.add_row(
            str(record["task_id"]),
            str(record["status"]),
            str(record["iteration"]),
            str(record["prompt"])[:60],
        )
    console.print(table)


@app.command()
def stop(
    task_id: str | None = typer.Argument(None, help="Task id; defaults to current"),
    workspace: Path | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Request cancellation for a running task."""
    root = _workspace(workspace)
    try:
        record = load_task(root, task_id) if task_id else load_current(root)
    except ValueError as exc:
        console.print(f"[ck.err]{exc}[/ck.err]")
        raise typer.Exit(1) from exc
    if record is None:
        console.print("[ck.err]task not found[/ck.err]")
        raise typer.Exit(1)
    if record.status in {"succeeded", "failed", "interrupted"}:
        console.print(f"[ck.dim]task {record.task_id} is already {record.status}[/ck.dim]")
        return
    request_cancel(root, record.task_id)
    console.print(f"cancel requested for {record.task_id}")


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
