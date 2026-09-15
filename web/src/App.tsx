import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchCheckpoints,
  fetchDiff,
  fetchFile,
  fetchTask,
  fetchTree,
  getConfig,
  isDesktopRpc,
  listSessions,
  loadSession,
  pickDirectory,
  postTaskAction,
  retryTask,
  rollbackCheckpoint,
  startTask,
  subscribeEvents,
  updateConfig,
  type CheckpointView,
  type SessionMeta,
  type TaskView,
} from "./desktopAgent";
import { apiUrl, wsUrl } from "./apiBase";
import { Markdown } from "./markdown";

type AgentEvent = { id?: string; type: string; payload: Record<string, unknown> };
type Tab = "files" | "diff" | "checkpoints" | "output";

const STATUS_META: Record<string, { label: string; pill: string }> = {
  pending: { label: "待运行", pill: "pill-idle" },
  running: { label: "运行中", pill: "pill-running" },
  waiting_approval: { label: "等待确认", pill: "pill-running" },
  succeeded: { label: "已完成", pill: "pill-done" },
  failed: { label: "失败", pill: "pill-failed" },
  interrupted: { label: "已中断", pill: "pill-failed" },
};

const EXAMPLE_PROMPTS = [
  "修复这个仓库里失败的单元测试，并解释根因。",
  "给现有模块补充类型标注和 docstring，不改行为。",
  "审查最近的改动，找出潜在 bug 并给出修复建议。",
];

const MODEL_PRESETS = ["glm-4.7", "glm-4.7-flash", "gpt-4o-mini", "gpt-4o"];

const TOOL_META: Record<string, string> = {
  read: "读文件",
  write: "写文件",
  write_file: "写文件",
  create_file: "写文件",
  edit: "编辑",
  edit_file: "编辑",
  bash: "终端",
  shell: "终端",
  search: "搜索",
  grep: "搜索",
  list: "列目录",
  ls: "列目录",
  git: "Git",
  abort: "停止任务",
  interrupt: "停止任务",
  agent: "子代理",
  plan: "工作计划",
};

function toolLabel(name: string): string {
  return TOOL_META[name] ?? name;
}

function relTime(iso: string): string {
  if (!iso || iso === "—") return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const diff = Date.now() - t;
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}小时`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)}天`;
  return new Date(t).toISOString().slice(0, 10);
}

function isToday(iso: string): boolean {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return false;
  return new Date(t).toDateString() === new Date().toDateString();
}

function fmtElapsed(ms: number): string {
  if (ms < 0) ms = 0;
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec} 秒`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} 分 ${sec % 60} 秒`;
  const hr = Math.floor(min / 60);
  return `${hr} 小时 ${min % 60} 分`;
}

function diffStats(diff: string): { files: number; adds: number; dels: number } {
  let files = 0;
  let adds = 0;
  let dels = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("diff --git ")) files += 1;
    else if (line.startsWith("+++")) continue;
    else if (line.startsWith("---")) continue;
    else if (line.startsWith("+")) adds += 1;
    else if (line.startsWith("-")) dels += 1;
  }
  return { files, adds, dels };
}

const REPO_STORAGE_KEY = "coderking.repository";

/* ── icons ─────────────────────────────────────────────────────────── */

function IconMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none">
      <path
        d="M12 3v18M5.6 5.6l12.8 12.8M3 12h18M5.6 18.4L18.4 5.6"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        opacity="0.9"
      />
    </svg>
  );
}

function IconSend() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none">
      <path
        d="M12 19V5M6 11l6-6 6 6"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconStop() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2.5" />
    </svg>
  );
}

function IconFolder() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="15" height="15" fill="none">
      <path
        d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconPlus() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14" fill="none">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}

function IconChevron({ open }: { open: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width="12"
      height="12"
      fill="none"
      style={{
        transform: open ? "rotate(90deg)" : "none",
        transition: "transform 0.15s ease",
        flexShrink: 0,
      }}
    >
      <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

function pytestHeadline(text: string): { ok: boolean; text: string } {
  if (!text.trim()) return { ok: false, text: "" };
  const passed = text.match(/(\d+) passed/);
  const failed = text.match(/(\d+) failed/);
  if (passed || failed) {
    const parts = [
      passed ? `${passed[1]} passed` : null,
      failed ? `${failed[1]} failed` : null,
    ].filter(Boolean);
    return { ok: !failed, text: parts.join(" · ") };
  }
  return { ok: false, text: text.split("\n")[0].slice(0, 120) };
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return String(n);
}

function eventKey(event: AgentEvent, index: number): string {
  return event.id ?? `${event.type}-${index}`;
}

/* ── transcript model: fold the event stream into chat blocks ───────── */

type ToolCall = {
  id: string;
  tool: string;
  status: string;
  arguments?: Record<string, unknown>;
  preview?: string;
};

type Block =
  | { kind: "user"; id: string; text: string }
  | { kind: "assistant"; id: string; text: string; streaming: boolean }
  | { kind: "tools"; id: string; calls: ToolCall[]; subagent?: string }
  | { kind: "status"; id: string; text: string; tone: "info" | "warn" | "ok" };

function flushStream(blocks: Block[]): Block[] {
  const last = blocks[blocks.length - 1];
  if (last?.kind === "assistant" && last.streaming) {
    return [...blocks.slice(0, -1), { ...last, streaming: false }];
  }
  return blocks;
}

function foldEvent(blocks: Block[], ev: AgentEvent, key: string): Block[] {
  switch (ev.type) {
    case "steer":
    case "follow_up": {
      const text = String(ev.payload.content ?? "").trim();
      if (!text) return blocks;
      return [...flushStream(blocks), { kind: "user", id: key, text }];
    }
    case "content_delta": {
      const text = String(ev.payload.text ?? "");
      if (!text) return blocks;
      const last = blocks[blocks.length - 1];
      if (last?.kind === "assistant" && last.streaming) {
        return [...blocks.slice(0, -1), { ...last, text: last.text + text }];
      }
      return [...blocks, { kind: "assistant", id: `stream-${key}`, text, streaming: true }];
    }
    case "tool_call": {
      const next = flushStream(blocks);
      const call: ToolCall = {
        id: key,
        tool: String(ev.payload.tool ?? ""),
        status: String(ev.payload.status ?? ""),
        arguments: ev.payload.arguments as Record<string, unknown> | undefined,
        preview: ev.payload.preview === undefined ? undefined : String(ev.payload.preview),
      };
      const subagent = ev.payload.subagent === undefined ? undefined : String(ev.payload.subagent);
      const tail = next[next.length - 1];
      if (tail?.kind === "tools" && tail.calls.length < 50 && tail.subagent === subagent) {
        return [...next.slice(0, -1), { ...tail, calls: [...tail.calls, call] }];
      }
      return [...next, { kind: "tools", id: `tools-${key}`, calls: [call], subagent }];
    }
    case "subagent_start":
      return [
        ...blocks,
        {
          kind: "status",
          id: key,
          text: `子代理启动 · ${String(ev.payload.description ?? "")}（${String(ev.payload.agent_type ?? "")}）`,
          tone: "info",
        },
      ];
    case "subagent_end": {
      const ok = Boolean(ev.payload.ok);
      const desc = String(ev.payload.description ?? "");
      const calls = Number(ev.payload.tool_calls ?? 0);
      const summary = String(ev.payload.summary ?? "").slice(0, 120);
      return [
        ...blocks,
        {
          kind: "status",
          id: key,
          text: ok
            ? `子代理完成 · ${desc} · ${calls} 次工具调用 · ${summary}`
            : `子代理失败 · ${desc} · ${summary}`,
          tone: ok ? "ok" : "warn",
        },
      ];
    }
    case "approval_required":
      return [
        ...flushStream(blocks),
        {
          kind: "status",
          id: key,
          text: `等待确认 · ${String(ev.payload.tool ?? "")}`,
          tone: "warn",
        },
      ];
    case "error":
      return [
        ...flushStream(blocks),
        { kind: "status", id: key, text: `出错 · ${String(ev.payload.message ?? "")}`, tone: "warn" },
      ];
    case "done": {
      const ok = Boolean(ev.payload.ok);
      const summary = String(ev.payload.summary ?? "");
      return [
        ...flushStream(blocks),
        { kind: "status", id: key, text: ok ? "任务完成" : `任务结束 · ${summary}`, tone: ok ? "ok" : "warn" },
      ];
    }
    case "context_compressed": {
      const before = Number(ev.payload.before_tokens ?? 0);
      const after = Number(ev.payload.after_tokens ?? 0);
      return [
        ...blocks,
        { kind: "status", id: key, text: `上下文压缩 ${fmtTokens(before)} → ${fmtTokens(after)} tokens`, tone: "info" },
      ];
    }
    case "context_micro_compacted": {
      const before = Number(ev.payload.before_tokens ?? 0);
      const after = Number(ev.payload.after_tokens ?? 0);
      const count = Number(ev.payload.tool_results_compacted ?? 0);
      return [
        ...blocks,
        {
          kind: "status",
          id: key,
          text: `微压缩 ${fmtTokens(before)} → ${fmtTokens(after)} tokens（${count} 条工具结果）`,
          tone: "info",
        },
      ];
    }
    case "checkpoint":
      return [
        ...blocks,
        {
          kind: "status",
          id: key,
          text: `检查点 ${String(ev.payload.path ?? "")}（${String(ev.payload.status ?? "")}）`,
          tone: "info",
        },
      ];
    case "sandbox_status":
      return [
        ...blocks,
        {
          kind: "status",
          id: key,
          text: `沙箱 ${String(ev.payload.backend ?? "")} · ${String(ev.payload.status ?? "")}`,
          tone: "info",
        },
      ];
    default:
      return blocks;
  }
}

function buildTranscript(events: AgentEvent[], finalize = false): Block[] {
  let blocks: Block[] = [];
  events.forEach((ev, i) => {
    blocks = foldEvent(blocks, ev, eventKey(ev, i));
  });
  return finalize ? flushStream(blocks) : blocks;
}

/* ── subcomponents ─────────────────────────────────────────────────── */

function ArgumentRows({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args ?? {});
  if (!entries.length) return null;
  return (
    <div className="tool-args">
      {entries.map(([k, v]) => (
        <div className="tool-arg-row" key={k}>
          <span className="tool-arg-key">{k}</span>
          <span className="tool-arg-val">{typeof v === "string" ? v : JSON.stringify(v)}</span>
        </div>
      ))}
    </div>
  );
}

function ToolGroup({ block }: { block: Extract<Block, { kind: "tools" }> }) {
  const [open, setOpen] = useState(false);
  const errors = block.calls.filter((c) => c.status === "error").length;
  const last = block.calls[block.calls.length - 1];
  return (
    <div className={`tool-group ${block.subagent ? "tool-group-subagent" : ""}`}>
      <button className="tool-group-head" onClick={() => setOpen(!open)} type="button">
        <IconChevron open={open} />
        <span className="tool-group-title">
          {block.subagent ? (
            <>
              <span className="tool-group-sub-badge">子代理</span> {block.subagent}{" "}
              <span className="tool-group-count">· {block.calls.length}</span>
            </>
          ) : (
            <>
              工具调用 <span className="tool-group-count">· {block.calls.length}</span>
            </>
          )}
        </span>
        {errors > 0 ? <span className="tool-group-errors">{errors} 失败</span> : null}
        {!open && last ? (
          <span className="tool-group-last">
            {toolLabel(last.tool)}
            {last.preview ? ` · ${last.preview.split("\n")[0].slice(0, 60)}` : ""}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="tool-group-body">
          {block.calls.map((call) => (
            <div className="tool-item" key={call.id}>
              <div className="tool-item-head">
                <span className={`tool-mark ${call.status === "ok" ? "ok" : call.status === "error" ? "error" : ""}`} />
                <span className="tool-item-name">{toolLabel(call.tool)}</span>
                <span className="tool-item-status">{call.status}</span>
              </div>
              {call.arguments ? <ArgumentRows args={call.arguments} /> : null}
              {call.preview ? <pre className="tool-preview">{call.preview}</pre> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function PlanCard({ plan }: { plan: { title: string; done: boolean }[] }) {
  const activeIdx = plan.findIndex((item) => !item.done);
  const doneCount = plan.filter((item) => item.done).length;
  return (
    <div className="plan-card">
      <div className="plan-head">
        工作计划
        <span className="plan-count">
          {doneCount}/{plan.length}
        </span>
      </div>
      <ul className="plan-list">
        {plan.map((item, i) => (
          <li className={`plan-item ${i === activeIdx ? "active" : ""}`} key={`${i}-${item.title}`}>
            <span className={`plan-mark ${item.done ? "done" : i === activeIdx ? "progress" : ""}`}>
              {item.done ? "✓" : i === activeIdx ? "◐" : "○"}
            </span>
            <span className={item.done ? "plan-title-done" : ""}>{item.title}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ApprovalCard({
  tool,
  reason,
  arguments: args,
  onApprove,
  onReject,
}: {
  tool: string;
  reason: string;
  arguments: Record<string, unknown>;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <div className="card approval-card">
      <div className="approval-head">
        <span className="approval-badge">审批</span>
        <span className="approval-tool">{tool}</span>
        {reason ? <span className="approval-reason">{reason}</span> : null}
      </div>
      <ArgumentRows args={args} />
      <div className="approval-actions">
        <button className="btn btn-primary" onClick={onApprove} type="button">
          允许 <span className="kbd-hint">⌘⏎</span>
        </button>
        <button className="btn btn-secondary" onClick={onReject} type="button">
          拒绝 <span className="kbd-hint">Esc</span>
        </button>
      </div>
    </div>
  );
}

function ContextMeter({ context, tokens }: { context?: TaskView["context"]; tokens: TaskView["tokens"] }) {
  const est = context?.estimated_tokens ?? 0;
  const comp = context?.compression_count ?? 0;
  const ratio = Math.min(1, est / 200_000);
  return (
    <div className="ctx-meter" title={`上下文约 ${fmtTokens(est)} tokens · 压缩 ${comp} 次 · 输入 ${fmtTokens(tokens.prompt)} / 输出 ${fmtTokens(tokens.completion)}`}>
      <div className="ctx-bar">
        <div className="ctx-fill" style={{ width: `${Math.max(est > 0 ? 4 : 0, ratio * 100)}%` }} />
      </div>
      <span className="ctx-label">
        {est > 0 ? fmtTokens(est) : "—"}
        {comp > 0 ? <span className="ctx-comp"> · 压缩{comp}</span> : null}
      </span>
    </div>
  );
}

function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return (
      <div className="flex h-full items-center justify-center text-[14px]" style={{ color: "var(--text-3)" }}>
        还没有改动。任务完成后这里显示 Diff。
      </div>
    );
  }
  const files = diff.split("\n").filter((l) => l.startsWith("+++ "));
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 p-4">
      {files.length > 1 ? (
        <div className="diff-stats">
          {files.length} 个文件改动
        </div>
      ) : null}
      <pre className="code-block min-h-0 flex-1">
        {diff.split("\n").map((line, i) => {
          const cls = line.startsWith("+++") || line.startsWith("---")
            ? ""
            : line.startsWith("+")
              ? "diff-add"
              : line.startsWith("-")
                ? "diff-del"
                : line.startsWith("@@")
                  ? "diff-hunk"
                  : "";
          return (
            <div className={cls} key={`${i}-${line.slice(0, 24)}`}>
              {line || " "}
            </div>
          );
        })}
      </pre>
    </div>
  );
}

/* ── app ───────────────────────────────────────────────────────────── */

export default function App() {
  const [prompt, setPrompt] = useState("");
  const [repository, setRepository] = useState(() => localStorage.getItem(REPO_STORAGE_KEY) ?? "");
  const [task, setTask] = useState<TaskView | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [files, setFiles] = useState<string[]>([]);
  const [activeFile, setActiveFile] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [diff, setDiff] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hitl, setHitl] = useState<AgentEvent | null>(null);
  const [composerText, setComposerText] = useState("");
  const [tab, setTab] = useState<Tab>("files");
  const [sessions, setSessions] = useState<SessionMeta[] | null>(null);
  const [activeSession, setActiveSession] = useState("");
  const [checkpoints, setCheckpoints] = useState<CheckpointView[]>([]);
  const [confirmRollback, setConfirmRollback] = useState("");
  const [autoApprove, setAutoApprove] = useState(false);
  const [model, setModel] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState("off");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [workCollapsed, setWorkCollapsed] = useState(false);
  const [tick, setTick] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const taskIdRef = useRef("");
  const seenIdsRef = useRef<Set<string>>(new Set());
  const desktopRpc = isDesktopRpc();
  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const running = task?.status === "running";

  const blocks = useMemo(() => buildTranscript(events, !running), [events, running]);

  const output = useMemo(
    () =>
      events
        .filter((e) => e.type === "terminal" || e.type === "test_result")
        .map((e) => String(e.payload.text ?? ""))
        .join("\n\n"),
    [events],
  );

  const streamingActive = useMemo(
    () => blocks.some((b) => b.kind === "assistant" && b.streaming),
    [blocks],
  );

  useEffect(() => {
    taskIdRef.current = task?.task_id ?? "";
  }, [task?.task_id]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [blocks.length, streamingActive, hitl]);

  useEffect(() => {
    if (repository.trim()) localStorage.setItem(REPO_STORAGE_KEY, repository.trim());
  }, [repository]);

  useEffect(() => {
    if (!desktopRpc) return;
    void getConfig()
      .then((cfg) => {
        if (cfg?.model) setModel(cfg.model);
        if (cfg?.reasoning_effort) setReasoningEffort(cfg.reasoning_effort);
      })
      .catch(() => undefined);
  }, [desktopRpc]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  const elapsedMs = useMemo(() => {
    const timing = task?.timing;
    if (!timing?.created_at) return 0;
    const start = Date.parse(timing.created_at);
    if (Number.isNaN(start)) return 0;
    const end = running
      ? Date.now()
      : Date.parse(timing.finished_at ?? timing.updated_at ?? "") || Date.now();
    return end - start;
  }, [task?.timing, running, task?.status, tick]);

  async function onModelChange(next: string) {
    setModel(next);
    try {
      await updateConfig({ model: next });
    } catch {
      /* keep optimistic value; next getConfig resyncs */
    }
  }

  async function onReasoningChange(next: string) {
    setReasoningEffort(next);
    try {
      await updateConfig({ reasoning_effort: next });
    } catch {
      /* keep optimistic value; next getConfig resyncs */
    }
  }

  const filteredSessions = useMemo(() => {
    const list = sessions ?? [];
    const q = searchText.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (s) => s.prompt.toLowerCase().includes(q) || s.session_id.toLowerCase().includes(q),
    );
  }, [sessions, searchText]);

  async function refreshSessions() {
    if (!desktopRpc) return;
    try {
      setSessions(await listSessions(30));
    } catch {
      setSessions(null);
    }
  }

  useEffect(() => {
    void refreshSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktopRpc, task?.status === "succeeded" || task?.status === "failed"]);

  function appendEvent(event: AgentEvent) {
    if (event.id) {
      if (seenIdsRef.current.has(event.id)) return;
      seenIdsRef.current.add(event.id);
    }
    setEvents((prev) => [...prev, event]);
    if (event.type === "approval_required") setHitl(event);
    if (event.type === "done") setHitl(null);
    const id = taskIdRef.current;
    if (
      id &&
      (event.type === "file_change" ||
        event.type === "done" ||
        event.type === "agent_status" ||
        event.type === "plan_update")
    ) {
      void refreshTask(id);
      void loadTree(id);
      // the done event can outrun the backend's final task-state write — re-poll once
      if (event.type === "done") {
        window.setTimeout(() => {
          if (taskIdRef.current === id) void refreshTask(id);
        }, 600);
      }
    }
    if (event.type === "checkpoint" || event.type === "done") {
      setCheckpoints([]);
    }
  }

  useEffect(() => {
    if (desktopRpc) {
      return subscribeEvents(appendEvent);
    }
    return () => {
      wsRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktopRpc]);

  async function refreshTask(id: string) {
    if (desktopRpc) {
      setTask(await fetchTask(id));
      setDiff(await fetchDiff(id));
      return;
    }
    const res = await fetch(apiUrl(`/api/tasks/${id}`));
    if (!res.ok) return;
    setTask((await res.json()) as TaskView);
    const diffRes = await fetch(apiUrl(`/api/tasks/${id}/diff`));
    if (diffRes.ok) {
      const data = (await diffRes.json()) as { diff: string };
      setDiff(data.diff);
    }
  }

  async function loadTree(id: string) {
    if (desktopRpc) {
      const tree = await fetchTree(id);
      setFiles(tree);
      if (tree[0] && !tree.includes(activeFile)) setActiveFile(tree[0]);
      return;
    }
    const res = await fetch(apiUrl(`/api/tasks/${id}/tree`));
    if (!res.ok) return;
    const data = (await res.json()) as { files: string[] };
    setFiles(data.files);
    if (data.files[0] && !data.files.includes(activeFile)) setActiveFile(data.files[0]);
  }

  useEffect(() => {
    if (!task?.task_id || tab !== "checkpoints") return;
    let cancelled = false;
    fetchCheckpoints(task.task_id)
      .then((list) => {
        if (!cancelled) setCheckpoints(list);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [tab, task?.task_id, task?.checkpoints?.count, checkpoints.length === 0]);

  useEffect(() => {
    if (!task?.task_id || !activeFile) return;
    if (desktopRpc) {
      fetchFile(task.task_id, activeFile)
        .then((content) => setFileContent(content))
        .catch(() => undefined);
      return;
    }
    fetch(apiUrl(`/api/tasks/${task.task_id}/file?path=${encodeURIComponent(activeFile)}`))
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setFileContent(String(data.content ?? ""));
      })
      .catch(() => undefined);
  }, [activeFile, desktopRpc, task?.task_id]);

  function connectWs(id: string) {
    if (desktopRpc) return;
    wsRef.current?.close();
    const socket = new WebSocket(wsUrl(`/ws/tasks/${id}`));
    wsRef.current = socket;
    socket.onmessage = (msg) => {
      appendEvent(JSON.parse(msg.data) as AgentEvent);
    };
  }

  function resetConversation() {
    setTask(null);
    setEvents([]);
    setFiles([]);
    setActiveFile("");
    setFileContent("");
    setDiff("");
    setHitl(null);
    setCheckpoints([]);
    setError("");
    seenIdsRef.current = new Set();
  }

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    if (busy || !prompt.trim()) return;
    setBusy(true);
    setError("");
    setEvents([]);
    setHitl(null);
    seenIdsRef.current = new Set();
    try {
      if (desktopRpc) {
        const created = await startTask(prompt, repository || ".", autoApprove, activeSession || null);
        await switchToTask(created.task_id);
        if (!repository.trim() || repository.trim() === ".") {
          void getConfig().then((cfg) => {
            if (cfg?.workspace) setRepository(cfg.workspace);
          });
        }
        return;
      }
      const res = await fetch(apiUrl("/api/tasks"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          repository: repository || ".",
          auto_approve: false,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const created = (await res.json()) as TaskView;
      setTask(created);
      connectWs(created.task_id);
      await loadTree(created.task_id);
      await refreshTask(created.task_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to start task");
    } finally {
      setBusy(false);
    }
  }

  async function switchToTask(id: string) {
    const view = await fetchTask(id);
    setTask(view);
    taskIdRef.current = id;
    (view.events ?? []).forEach(appendEvent);
    await loadTree(id);
    await refreshTask(id);
    if (!desktopRpc) connectWs(id);
  }

  async function onRetry() {
    if (!task) return;
    setBusy(true);
    setError("");
    try {
      const next = await retryTask(task.task_id, null);
      setEvents([]);
      setHitl(null);
      seenIdsRef.current = new Set();
      await switchToTask(next.task_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "retry failed");
    } finally {
      setBusy(false);
    }
  }

  async function act(path: "interrupt" | "approve" | "reject" | "rollback" | "accept") {
    if (!task) return;
    if (desktopRpc) {
      await postTaskAction(task.task_id, path);
    } else {
      await fetch(apiUrl(`/api/tasks/${task.task_id}/${path}`), { method: "POST" });
    }
    if (path === "rollback" || path === "accept") {
      await refreshTask(task.task_id);
      setCheckpoints([]);
    }
    if (path === "approve" || path === "reject") setHitl(null);
  }

  async function sendControl(path: "steer" | "follow-up", content: string) {
    if (!task || !content.trim()) return;
    if (desktopRpc) {
      await postTaskAction(task.task_id, path, content.trim());
    } else {
      await fetch(apiUrl(`/api/tasks/${task.task_id}/${path}`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: content.trim() }),
      });
    }
    setComposerText("");
    if (composerRef.current) composerRef.current.style.height = "auto";
  }

  async function onComposerSubmit(ev: FormEvent) {
    ev.preventDefault();
    if (!composerText.trim()) return;
    await sendControl(running ? "steer" : "follow-up", composerText);
  }

  function onComposerKeyDown(ev: KeyboardEvent<HTMLTextAreaElement>) {
    if ((ev.metaKey || ev.ctrlKey) && ev.key === "Enter") {
      ev.preventDefault();
      if (hitl) {
        void act("approve");
        return;
      }
      if (composerText.trim()) void sendControl(running ? "steer" : "follow-up", composerText);
    }
  }

  useEffect(() => {
    function globalKeys(ev: globalThis.KeyboardEvent) {
      if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "n") {
        ev.preventDefault();
        resetConversation();
        setPrompt("");
        setActiveSession("");
      }
      if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "k") {
        ev.preventDefault();
        setSearchOpen((open) => !open);
        setSearchText("");
      }
      if (ev.key === "Escape") {
        if (searchOpen) {
          setSearchOpen(false);
          setSearchText("");
          return;
        }
        if (hitl) {
          void act("reject");
        } else if (task?.status === "running") {
          void act("interrupt");
        }
      }
    }
    window.addEventListener("keydown", globalKeys);
    return () => window.removeEventListener("keydown", globalKeys);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hitl, task?.status, task?.task_id, searchOpen]);

  async function onPickSession(meta: SessionMeta) {
    setActiveSession(meta.session_id);
    setBusy(true);
    try {
      const loaded = await loadSession(meta.session_id);
      if (!loaded) return;
      const seed: AgentEvent[] = [];
      loaded.messages.forEach((msg, i) => {
        if (!msg.text.trim()) return;
        if (msg.role === "user") {
          seed.push({ type: "follow_up", payload: { content: msg.text }, id: `hist-u-${i}` });
        } else if (msg.role === "assistant") {
          seed.push({ type: "content_delta", payload: { text: msg.text }, id: `hist-a-${i}` });
        }
      });
      seenIdsRef.current = new Set(seed.map((e) => e.id as string));
      setEvents(seed);
      setFiles([]);
      setActiveFile("");
      setFileContent("");
      setDiff("");
      setCheckpoints([]);
      setHitl(null);
      setError("");
      setTask({
        task_id: "",
        prompt: "",
        status: "pending",
        role: "assistant",
        iteration: 0,
        plan: [],
        changed_files: [],
        test_results: "",
        sandbox: { backend: "", status: "" },
        tokens: meta.tokens,
        session_id: meta.session_id,
        model: undefined,
        errors: [],
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to load session");
    } finally {
      setBusy(false);
    }
  }

  const statusMeta = task ? STATUS_META[task.status] ?? { label: task.status, pill: "pill-idle" } : null;
  const tests = pytestHeadline(task?.test_results || "");
  const planItems = useMemo(() => task?.plan ?? [], [task?.plan]);
  const workspaceLabel = repository && repository !== "." ? repository : "";
  const conversationTitle =
    (task?.prompt || sessions?.find((s) => s.session_id === activeSession)?.prompt || "新任务")
      .split("\n")[0]
      .slice(0, 60) || "新任务";
  const hasWork = useMemo(
    () => blocks.some((b) => b.kind === "tools" || b.kind === "status"),
    [blocks],
  );
  const workToolCount = useMemo(
    () =>
      blocks.reduce((sum, b) => (b.kind === "tools" ? sum + b.calls.length : sum), 0),
    [blocks],
  );
  const diffSummary = useMemo(() => diffStats(diff), [diff]);

  const header = (
    <header
      className="flex h-14 shrink-0 items-center justify-between gap-4 px-5"
      style={{
        background: "var(--surface)",
        borderBottom: "1px solid var(--border)",
        paddingLeft: desktopRpc ? 84 : undefined,
      }}
    >
      <div className="flex min-w-0 items-center gap-2.5" style={{ color: "var(--accent)" }}>
        <IconMark />
        <span className="text-[15px] font-semibold" style={{ color: "var(--text)" }}>
          CoderKing
        </span>
        {workspaceLabel ? (
          <span className="truncate text-[12.5px]" style={{ color: "var(--text-3)" }} title={workspaceLabel}>
            {workspaceLabel.split("/").slice(-2).join("/")}
          </span>
        ) : null}
      </div>
      <div className="flex items-center gap-4">
        {task ? <ContextMeter context={task.context} tokens={task.tokens} /> : null}
        {statusMeta ? (
          <span className={statusMeta.pill}>
            <span className="pill-dot" />
            {statusMeta.label}
          </span>
        ) : (
          <span className="pill pill-idle">
            <span className="pill-dot" />
            空闲
          </span>
        )}
        <span className="text-[13.5px]" style={{ color: "var(--text-2)" }}>
          {task?.model ?? "未连接模型"}
        </span>
      </div>
    </header>
  );

  /* ── empty state: centered hero ─────────────────────────────── */
  if (!task) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        {header}
        <main className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-6 py-10">
          <div className="w-full max-w-2xl">
            <h1 className="text-center text-[30px] font-semibold leading-tight">有什么工程任务要处理？</h1>
            <p className="mt-2 text-center text-[15px]" style={{ color: "var(--text-2)" }}>
              描述任务，代理会自主浏览代码、修改、运行测试直到验证通过。
            </p>
            <form className="card mt-8 p-4" style={{ boxShadow: "var(--shadow-md)" }} onSubmit={onSubmit}>
              <textarea
                id="prompt"
                className="w-full resize-none bg-transparent px-2 py-1 text-[15px] leading-relaxed"
                style={{ border: "none", outline: "none", minHeight: 96 }}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
              <div className="composer-toolbar mt-1">
                <label className="composer-tool" title="审批模式：自动批准时工具调用不再逐个确认">
                  <span className="composer-tool-icon" aria-hidden="true">🛡</span>
                  <select
                    className="composer-select"
                    onChange={(e) => setAutoApprove(e.target.value === "auto")}
                    value={autoApprove ? "auto" : "manual"}
                  >
                    <option value="manual">每次审批</option>
                    <option value="auto">自动批准</option>
                  </select>
                </label>
                {desktopRpc ? (
                  <label className="composer-tool" title="推理等级（对下一个任务生效）">
                    <span className="composer-tool-icon" aria-hidden="true">🧠</span>
                    <select
                      className="composer-select"
                      onChange={(e) => void onReasoningChange(e.target.value)}
                      value={reasoningEffort}
                    >
                      <option value="off">关闭</option>
                      <option value="low">低</option>
                      <option value="medium">中</option>
                      <option value="high">高</option>
                      <option value="ultra">最高</option>
                    </select>
                  </label>
                ) : null}
                {desktopRpc && model ? (
                  <label className="composer-tool ml-auto" title="模型（对下一个任务生效）">
                    <select
                      className="composer-select"
                      onChange={(e) => void onModelChange(e.target.value)}
                      value={model}
                    >
                      {[...new Set([model, ...MODEL_PRESETS])].map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </div>
              <div className="mt-3 flex items-center gap-3 border-t pt-3" style={{ borderColor: "var(--border)" }}>
                <label
                  className="flex min-w-0 flex-1 items-center gap-2 text-[13.5px]"
                  style={{ color: "var(--text-2)" }}
                >
                  <IconFolder />
                  <span className="sr-only">仓库路径</span>
                  <input
                    id="repo"
                    className="min-w-0 flex-1 bg-transparent text-[13.5px]"
                    style={{ border: "none", outline: "none", color: "var(--text)" }}
                    value={repository}
                    onChange={(e) => setRepository(e.target.value)}
                    placeholder="/path/to/repository"
                  />
                </label>
                {desktopRpc ? (
                  <button
                    className="btn btn-ghost"
                    onClick={() => {
                      void pickDirectory().then((dir) => {
                        if (dir) setRepository(dir);
                      });
                    }}
                    type="button"
                  >
                    浏览…
                  </button>
                ) : null}
                <button className="btn btn-primary" disabled={busy || !prompt.trim()} type="submit">
                  {busy ? "启动中…" : "运行任务"}
                </button>
              </div>
            </form>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {EXAMPLE_PROMPTS.map((example) => (
                <button className="example-chip" key={example} onClick={() => setPrompt(example)} type="button">
                  {example}
                </button>
              ))}
            </div>
            {error ? (
              <p className="mt-4 text-center text-[14px]" style={{ color: "var(--err)" }}>
                {error}
              </p>
            ) : null}
            {sessions && sessions.length > 0 ? (
              <div className="mt-10">
                <div className="session-section-title">最近会话</div>
                <ul>
                  {sessions.slice(0, 5).map((meta) => (
                    <li key={meta.session_id}>
                      <button className="session-row" onClick={() => void onPickSession(meta)} type="button">
                        <span className="session-prompt">{meta.prompt || meta.session_id}</span>
                        <span className="session-meta">
                          {meta.updated_at} · {fmtTokens(meta.tokens.prompt + meta.tokens.completion)} tokens
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </main>
      </div>
    );
  }

  /* ── workspace state ────────────────────────────────────────── */
  return (
    <div className="flex h-full min-h-0 flex-col">
      {header}
      <div className="flex min-h-0 flex-1">
        {/* session sidebar (desktop RPC only) */}
        {desktopRpc ? (
          <aside className="session-sidebar" style={{ borderRight: "1px solid var(--border)" }}>
            <button
              className="btn btn-ghost new-session-btn"
              onClick={() => {
                resetConversation();
                setPrompt("");
                setActiveSession("");
              }}
              type="button"
            >
              <IconPlus /> 新会话 <span className="kbd-hint">⌘N</span>
            </button>
            {workspaceLabel ? (
              <div className="workspace-label" title={workspaceLabel}>
                <IconFolder /> <span className="truncate">{workspaceLabel}</span>
              </div>
            ) : null}
            {searchOpen ? (
              <input
                autoFocus
                className="session-search"
                placeholder="搜索会话…（Esc 关闭）"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                type="text"
              />
            ) : null}
            <div className="session-section-title">
              会话
              <button className="session-search-toggle" onClick={() => setSearchOpen(true)} title="搜索（⌘K）" type="button">
                ⌘K
              </button>
            </div>
            <ul className="min-h-0 flex-1 overflow-y-auto">
              {[
                { label: "", items: filteredSessions.filter((s) => !searchText.trim() && isToday(s.updated_at)) },
                { label: "更早", items: filteredSessions.filter((s) => searchText.trim() || !isToday(s.updated_at)) },
              ].map((group) =>
                group.items.length > 0 ? (
                  <li key={group.label || "today"}>
                    {group.label ? <div className="session-group-title">{group.label}</div> : null}
                    <ul>
                      {group.items.map((meta) => (
                        <li key={meta.session_id}>
                          <button
                            className={`session-row ${meta.session_id === activeSession ? "active" : ""}`}
                            onClick={() => void onPickSession(meta)}
                            type="button"
                          >
                            <span className="session-prompt">
                              {meta.running ? <span className="session-running-dot" /> : null}
                              {meta.prompt || meta.session_id}
                            </span>
                            <span className="session-meta">
                              {relTime(meta.updated_at)} · {fmtTokens(meta.tokens.prompt + meta.tokens.completion)}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </li>
                ) : null,
              )}
              {sessions && sessions.length === 0 ? (
                <li className="px-3 py-2 text-[12.5px]" style={{ color: "var(--text-3)" }}>
                  还没有历史会话
                </li>
              ) : null}
              {sessions && sessions.length > 0 && filteredSessions.length === 0 ? (
                <li className="px-3 py-2 text-[12.5px]" style={{ color: "var(--text-3)" }}>
                  没有匹配的会话
                </li>
              ) : null}
            </ul>
          </aside>
        ) : null}

        {/* conversation */}
        <section className="flex min-h-0 flex-1 flex-col" style={{ borderRight: "1px solid var(--border)" }}>
          <div className="conv-header">
            <div className="min-w-0">
              <div className="conv-title">{conversationTitle}</div>
              {workspaceLabel ? (
                <div className="conv-breadcrumb" title={workspaceLabel}>
                  <IconFolder /> {workspaceLabel.split("/").slice(-2).join("/")}
                </div>
              ) : null}
            </div>
          </div>
          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            <div className="mx-auto flex max-w-3xl flex-col gap-4">
              {task.prompt ? (
                <div>
                  <div className="chat-role">任务</div>
                  <p className="text-[15px] leading-relaxed">{task.prompt}</p>
                </div>
              ) : null}

              {activeSession ? (
                <div className="status-line" style={{ color: "var(--text-3)" }}>
                  已恢复会话 {activeSession} — 发送新消息继续这个会话
                </div>
              ) : null}

              {planItems.length > 0 ? <PlanCard plan={planItems} /> : null}

              {hasWork ? (
                <button className="work-summary" onClick={() => setWorkCollapsed(!workCollapsed)} type="button">
                  <IconChevron open={!workCollapsed} />
                  <span>{running ? "工作中" : "已工作"} {fmtElapsed(elapsedMs)}</span>
                  <span className="work-summary-meta">
                    {workToolCount > 0 ? `${workToolCount} 次工具调用` : ""}
                  </span>
                </button>
              ) : null}

              {blocks.map((block) => {
                if (block.kind === "user") {
                  return (
                    <div key={block.id}>
                      <div className="chat-role chat-role-user">你</div>
                      <p className="user-msg">{block.text}</p>
                    </div>
                  );
                }
                if (block.kind === "assistant") {
                  return (
                    <div key={block.id}>
                      <div className="chat-role">CoderKing{block.streaming ? " · 生成中…" : ""}</div>
                      <div className="card reply-card">
                        <Markdown text={block.text} />
                        {block.streaming ? <span className="stream-cursor" /> : null}
                      </div>
                    </div>
                  );
                }
                if (workCollapsed && (block.kind === "tools" || block.kind === "status")) {
                  return null;
                }
                if (block.kind === "tools") {
                  return <ToolGroup block={block} key={block.id} />;
                }
                return (
                  <div className={`status-line ${block.tone === "warn" ? "status-warn" : block.tone === "ok" ? "status-ok" : ""}`} key={block.id}>
                    {block.text}
                  </div>
                );
              })}

              {hitl ? (
                <ApprovalCard
                  arguments={(hitl.payload.arguments as Record<string, unknown>) ?? {}}
                  onApprove={() => void act("approve")}
                  onReject={() => void act("reject")}
                  reason={String(hitl.payload.reason ?? "")}
                  tool={String(hitl.payload.tool ?? "")}
                />
              ) : null}

              {diffSummary.files > 0 && (task.changed_files.length > 0 || task.status === "succeeded") ? (
                <div className="diff-inline">
                  <IconChevron open />
                  <span className="diff-inline-text">
                    {diffSummary.files} 个文件已更改
                    <span className="diff-inline-add">+{diffSummary.adds}</span>
                    <span className="diff-inline-del">−{diffSummary.dels}</span>
                  </span>
                  <button className="btn btn-ghost btn-sm" onClick={() => void act("rollback")} type="button">
                    撤销
                  </button>
                </div>
              ) : null}

              {task.status === "failed" || task.status === "interrupted" ? (
                <div className="card fail-banner">
                  <div className="fail-text">
                    <span style={{ color: "var(--err)" }}>{task.status === "failed" ? "任务失败" : "任务已中断"}</span>
                    {task.errors.length ? (
                      <span style={{ color: "var(--text-2)" }}> · {task.errors[task.errors.length - 1].slice(0, 200)}</span>
                    ) : null}
                  </div>
                  <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void onRetry()} type="button">
                    重试
                  </button>
                </div>
              ) : null}

              {task.status === "succeeded" ? (
                <div className="card done-banner">
                  <div className="done-text text-[13.5px]" style={{ color: "var(--text-2)" }}>
                    任务完成，改动已就绪。
                    {tests.text ? (
                      <span style={{ color: tests.ok ? "var(--ok)" : "var(--err)" }}> 测试：{tests.text}</span>
                    ) : null}
                    <span style={{ color: "var(--text-3)" }}>
                      {" "}
                      · {task.changed_files.length} 个文件 · {fmtTokens(task.tokens.prompt)} →{" "}
                      {fmtTokens(task.tokens.completion)} tokens
                    </span>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button className="btn btn-primary btn-sm" onClick={() => void act("accept")} type="button">
                      采纳
                    </button>
                    <button className="btn btn-secondary btn-sm" onClick={() => void act("rollback")} type="button">
                      回滚
                    </button>
                  </div>
                </div>
              ) : null}

              {error ? (
                <p className="text-[14px]" style={{ color: "var(--err)" }}>
                  {error}
                </p>
              ) : null}
            </div>
          </div>

          {/* composer */}
          <form
            className="shrink-0 px-6 py-4"
            style={{ background: "var(--bg)", borderTop: "1px solid var(--border)" }}
            onSubmit={onComposerSubmit}
          >
            <div className="card composer-card mx-auto max-w-3xl p-3">
              <textarea
                id="composer"
                ref={composerRef}
                className="composer-input min-w-0 flex-1 resize-none bg-transparent px-1 text-[14.5px] leading-relaxed"
                style={{ border: "none", outline: "none", minHeight: 40, maxHeight: 200 }}
                placeholder={
                  hitl
                    ? "等待审批 — ⌘⏎ 允许，Esc 拒绝"
                    : running
                      ? "运行中 — 发送可改变方向（⌘⏎）"
                      : "继续跟进这个任务…（⌘⏎ 发送）"
                }
                rows={1}
                value={composerText}
                onChange={(e) => {
                  setComposerText(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = `${Math.min(200, e.target.scrollHeight)}px`;
                }}
                onKeyDown={onComposerKeyDown}
              />
              <div className="composer-toolbar">
                <label className="composer-tool" title="审批模式：自动批准时工具调用不再逐个确认">
                  <span className="composer-tool-icon" aria-hidden="true">🛡</span>
                  <select
                    className="composer-select"
                    onChange={(e) => setAutoApprove(e.target.value === "auto")}
                    value={autoApprove ? "auto" : "manual"}
                  >
                    <option value="manual">每次审批</option>
                    <option value="auto">自动批准</option>
                  </select>
                </label>
                {desktopRpc ? (
                  <label className="composer-tool" title="推理等级（对下一个任务生效）">
                    <span className="composer-tool-icon" aria-hidden="true">🧠</span>
                    <select
                      className="composer-select"
                      onChange={(e) => void onReasoningChange(e.target.value)}
                      value={reasoningEffort}
                    >
                      <option value="off">关闭</option>
                      <option value="low">低</option>
                      <option value="medium">中</option>
                      <option value="high">高</option>
                      <option value="ultra">最高</option>
                    </select>
                  </label>
                ) : null}
                <div className="ml-auto flex items-center gap-2">
                  {desktopRpc && model ? (
                    <label className="composer-tool" title="模型（对下一个任务生效）">
                      <select
                        className="composer-select"
                        onChange={(e) => void onModelChange(e.target.value)}
                        value={model}
                      >
                        {[...new Set([model, ...MODEL_PRESETS])].map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  {running ? (
                    <button className="btn btn-secondary btn-sm" onClick={() => void act("interrupt")} type="button">
                      <IconStop /> 停止 <span className="kbd-hint">Esc</span>
                    </button>
                  ) : null}
                  <button
                    aria-label={running ? "转向" : "跟进"}
                    className="send-round"
                    disabled={!composerText.trim()}
                    type="submit"
                  >
                    <IconSend />
                  </button>
                </div>
              </div>
            </div>
          </form>
        </section>

        {/* workspace panel */}
        <section
          className="flex min-h-0 w-[38%] min-w-[400px] max-w-[560px] flex-col"
          style={{ background: "var(--surface)" }}
        >
          <div className="flex shrink-0 items-center gap-5 px-5" style={{ borderBottom: "1px solid var(--border)" }}>
            {(["files", "diff", "checkpoints", "output"] as Tab[]).map((t) => (
              <button
                className={`tab ${tab === t ? "tab-active" : ""}`}
                key={t}
                onClick={() => setTab(t)}
                type="button"
              >
                {t === "files" ? "文件" : t === "diff" ? "Diff" : t === "checkpoints" ? "检查点" : "输出"}
              </button>
            ))}
            <span className="ml-auto text-[13px]" style={{ color: "var(--text-3)" }}>
              {tab === "files" && files.length ? `${files.length} 个文件` : ""}
              {tab === "checkpoints" && checkpoints.length ? `${checkpoints.length} 个检查点` : ""}
            </span>
          </div>

          {tab === "files" ? (
            <div className="grid min-h-0 flex-1 grid-cols-[200px_1fr]">
              <ul
                className="min-h-0 overflow-y-auto py-2 text-[13px]"
                style={{ borderRight: "1px solid var(--border)" }}
              >
                {files.map((file) => (
                  <li key={file}>
                    <button
                      className={`w-full cursor-pointer truncate px-3 py-1.5 text-left ${
                        file === activeFile ? "font-medium" : ""
                      }`}
                      style={
                        file === activeFile
                          ? { background: "var(--accent-soft)", color: "var(--accent)" }
                          : { color: "var(--text-2)" }
                      }
                      onClick={() => setActiveFile(file)}
                      type="button"
                    >
                      {file}
                      {task?.changed_files.includes(file) ? " ·" : ""}
                    </button>
                  </li>
                ))}
                {files.length === 0 ? (
                  <li className="px-3 py-1.5" style={{ color: "var(--text-3)" }}>
                    暂无文件
                  </li>
                ) : null}
              </ul>
              <pre className="code-block min-h-0 flex-1 rounded-none border-none">
                {fileContent || "选择左侧文件查看内容。"}
              </pre>
            </div>
          ) : null}

          {tab === "diff" ? <DiffView diff={diff} /> : null}

          {tab === "checkpoints" ? (
            <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-4">
              {checkpoints.map((cp) => (
                <div className="checkpoint-row" key={cp.checkpoint_id}>
                  <div className="checkpoint-main">
                    <div className="checkpoint-path">{cp.path}</div>
                    <div className="checkpoint-meta">
                      {cp.tool} · {cp.status}
                      {cp.recoverable ? " · 可恢复" : ""}
                      {cp.reason ? ` · ${cp.reason}` : ""}
                    </div>
                  </div>
                  {cp.recoverable ? (
                    confirmRollback === cp.checkpoint_id ? (
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => {
                          if (task?.task_id) {
                            void rollbackCheckpoint(task.task_id, cp.checkpoint_id).then(() => {
                              setConfirmRollback("");
                              setCheckpoints([]);
                              if (task.task_id) void refreshTask(task.task_id);
                            });
                          }
                        }}
                        type="button"
                      >
                        确认回滚？
                      </button>
                    ) : (
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => setConfirmRollback(cp.checkpoint_id)}
                        type="button"
                      >
                        回滚到此
                      </button>
                    )
                  ) : null}
                </div>
              ))}
              {checkpoints.length === 0 ? (
                <div className="flex flex-1 items-center justify-center text-[14px]" style={{ color: "var(--text-3)" }}>
                  还没有检查点。文件修改会产生检查点。
                </div>
              ) : null}
            </div>
          ) : null}

          {tab === "output" ? (
            <div className="flex min-h-0 flex-1 flex-col gap-3 p-4">
              {tests.text ? (
                <div
                  className="pill"
                  style={{
                    background: tests.ok ? "var(--ok-soft)" : "var(--err-soft)",
                    color: tests.ok ? "var(--ok)" : "var(--err)",
                    alignSelf: "flex-start",
                  }}
                >
                  <span className="pill-dot" style={{ background: "currentColor" }} />
                  测试 {tests.text}
                </div>
              ) : null}
              <pre className="code-block min-h-0 flex-1">{output || "等待沙箱输出…"}</pre>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
