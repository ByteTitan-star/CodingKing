import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchDiff,
  fetchFile,
  fetchTask,
  fetchTree,
  isDesktopRpc,
  pickDirectory,
  postTaskAction,
  startTask,
  subscribeEvents,
  type TaskView,
} from "./desktopAgent";
import { apiUrl, wsUrl } from "./apiBase";

type AgentEvent = { type: string; payload: Record<string, unknown> };

const STATUS_LABEL: Record<string, string> = {
  pending: "待运行",
  running: "运行中",
  waiting_approval: "等待确认",
  succeeded: "已完成",
  failed: "失败",
  interrupted: "已中断",
};

function pytestHeadline(text: string): string {
  if (!text.trim()) return "尚未运行测试";
  const passed = text.match(/(\d+) passed/);
  const failed = text.match(/(\d+) failed/);
  const parts = [
    passed ? `${passed[1]} passed` : null,
    failed ? `${failed[1]} failed` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" / ") : text.slice(0, 400);
}

function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return <pre className="p-4 text-xs text-slate-500">暂无任务级 Diff。</pre>;
  }
  return (
    <pre className="min-h-0 overflow-auto p-4 font-mono text-xs leading-6">
      {diff.split("\n").map((line, i) => {
        const color = line.startsWith("+")
          ? "text-emerald-300"
          : line.startsWith("-")
            ? "text-rose-300"
            : line.startsWith("@@")
              ? "text-sky-300"
              : "text-slate-300";
        return (
          <div className={color} key={`${i}-${line.slice(0, 24)}`}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}

export default function App() {
  const [prompt, setPrompt] = useState("Fix the failing unit tests in this repository.");
  const [repository, setRepository] = useState(".");
  const [task, setTask] = useState<TaskView | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [files, setFiles] = useState<string[]>([]);
  const [activeFile, setActiveFile] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [diff, setDiff] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hitl, setHitl] = useState<AgentEvent | null>(null);
  const [steerText, setSteerText] = useState("");
  const [followUpText, setFollowUpText] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const taskIdRef = useRef("");
  const desktopRpc = isDesktopRpc();

  const terminal = useMemo(
    () =>
      events
        .filter((e) => e.type === "terminal" || e.type === "test_result")
        .map((e) => String(e.payload.text ?? ""))
        .join("\n\n"),
    [events],
  );

  const replies = useMemo(
    () =>
      events
        .filter((e) => e.type === "done" || e.type === "error")
        .map((e) => String(e.payload.summary ?? e.payload.message ?? e.type)),
    [events],
  );

  useEffect(() => {
    taskIdRef.current = task?.task_id ?? "";
  }, [task?.task_id]);

  useEffect(() => {
    if (desktopRpc) {
      return subscribeEvents((event) => {
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
        }
      });
    }
    return () => {
      wsRef.current?.close();
    };
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
      if (tree[0]) setActiveFile(tree[0]);
      return;
    }
    const res = await fetch(apiUrl(`/api/tasks/${id}/tree`));
    if (!res.ok) return;
    const data = (await res.json()) as { files: string[] };
    setFiles(data.files);
    if (data.files[0]) setActiveFile(data.files[0]);
  }

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
      const event = JSON.parse(msg.data) as AgentEvent;
      setEvents((prev) => [...prev, event]);
      if (event.type === "approval_required") setHitl(event);
      if (event.type === "done") setHitl(null);
      if (
        event.type === "file_change" ||
        event.type === "done" ||
        event.type === "agent_status" ||
        event.type === "plan_update"
      ) {
        void refreshTask(id);
        void loadTree(id);
      }
    };
  }

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    setBusy(true);
    setError("");
    setEvents([]);
    setHitl(null);
    try {
      if (desktopRpc) {
        const created = await startTask(prompt, repository, false);
        const view = await fetchTask(created.task_id);
        setTask(view);
        await loadTree(created.task_id);
        await refreshTask(created.task_id);
        return;
      }
      const res = await fetch(apiUrl("/api/tasks"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, repository, auto_approve: false }),
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

  async function act(path: string) {
    if (!task) return;
    if (desktopRpc) {
      const action =
        path === "interrupt"
          ? "interrupt"
          : path === "approve"
            ? "approve"
            : path === "reject"
              ? "reject"
              : path === "rollback"
                ? "rollback"
                : path === "accept"
                  ? "accept"
                  : null;
      if (action) await postTaskAction(task.task_id, action);
    } else {
      await fetch(apiUrl(`/api/tasks/${task.task_id}/${path}`), { method: "POST" });
    }
    if (path === "rollback" || path === "accept") await refreshTask(task.task_id);
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
    if (path === "steer") setSteerText("");
    else setFollowUpText("");
  }

  const running = task?.status === "running";
  const waiting = task?.status === "waiting_approval";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
        <div>
          <div className="text-sm tracking-[0.18em] text-amber-200/80">CODERKING</div>
          <div className="text-lg font-semibold">Engineering Workspace</div>
        </div>
        <dl className="flex flex-wrap gap-4 text-sm text-slate-300">
          <div>
            <dt className="text-xs uppercase text-slate-500">Project</dt>
            <dd>{repository}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-slate-500">Model</dt>
            <dd>{task?.model ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-slate-500">Status</dt>
            <dd>{task ? STATUS_LABEL[task.status] ?? task.status : "空闲"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-slate-500">Role</dt>
            <dd>{task?.role ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-slate-500">Sandbox</dt>
            <dd>
              {task?.sandbox.backend ?? "idle"} / {task?.sandbox.status ?? "n/a"}
            </dd>
          </div>
        </dl>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(280px,1.1fr)_minmax(360px,1.4fr)_minmax(280px,1fr)]">
        <section className="flex min-h-0 flex-col border-r border-white/10">
          <h2 className="px-4 py-2 text-xs uppercase tracking-wider text-slate-500">Chat / Task</h2>
          <form className="space-y-2 border-b border-white/10 px-4 pb-3" onSubmit={onSubmit}>
            <label className="block text-sm" htmlFor="repo">
              仓库路径
              <div className="mt-1 flex gap-2">
                <input
                  id="repo"
                  className="min-w-0 flex-1 rounded-md border border-white/10 bg-[#12151c] px-3 py-2"
                  value={repository}
                  onChange={(e) => setRepository(e.target.value)}
                />
                {desktopRpc ? (
                  <button
                    className="min-h-11 shrink-0 cursor-pointer rounded-md border border-white/20 px-3"
                    onClick={() => {
                      void pickDirectory().then((dir) => {
                        if (dir) setRepository(dir);
                      });
                    }}
                    type="button"
                  >
                    浏览
                  </button>
                ) : null}
              </div>
            </label>
            <label className="block text-sm" htmlFor="prompt">
              任务
              <textarea
                id="prompt"
                className="mt-1 min-h-24 w-full rounded-md border border-white/10 bg-[#12151c] px-3 py-2"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </label>
            <div className="flex flex-wrap gap-2">
              <button
                className="min-h-11 cursor-pointer rounded-md bg-amber-300 px-4 font-medium text-black disabled:opacity-50"
                disabled={busy}
                type="submit"
              >
                {busy ? "启动中…" : "新建任务"}
              </button>
              <button
                className="min-h-11 cursor-pointer rounded-md border border-white/20 px-3"
                disabled={!task}
                onClick={() => void act("interrupt")}
                type="button"
              >
                Stop Task
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                className="min-h-11 cursor-pointer rounded-md border border-emerald-400/40 px-3 disabled:opacity-40"
                disabled={!waiting}
                onClick={() => void act("approve")}
                type="button"
              >
                Approve
              </button>
              <button
                className="min-h-11 cursor-pointer rounded-md border border-rose-400/40 px-3 disabled:opacity-40"
                disabled={!waiting}
                onClick={() => void act("reject")}
                type="button"
              >
                Reject
              </button>
              <button
                className="min-h-11 cursor-pointer rounded-md border border-amber-200/40 px-3"
                disabled={!task}
                onClick={() => void act("accept")}
                type="button"
              >
                Accept Changes
              </button>
              <button
                className="min-h-11 cursor-pointer rounded-md border border-white/20 px-3"
                disabled={!task}
                onClick={() => void act("rollback")}
                type="button"
              >
                Rollback Changes
              </button>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="block text-sm" htmlFor="steer">
                Steer（运行中转向）
                <textarea
                  id="steer"
                  className="mt-1 min-h-16 w-full rounded-md border border-white/10 bg-[#12151c] px-3 py-2"
                  disabled={!task || !running}
                  placeholder="停止当前方向，改为…"
                  value={steerText}
                  onChange={(e) => setSteerText(e.target.value)}
                />
              </label>
              <label className="block text-sm" htmlFor="follow-up">
                Follow-up（完成后跟进）
                <textarea
                  id="follow-up"
                  className="mt-1 min-h-16 w-full rounded-md border border-white/10 bg-[#12151c] px-3 py-2"
                  disabled={!task}
                  placeholder="任务完成后自动执行…"
                  value={followUpText}
                  onChange={(e) => setFollowUpText(e.target.value)}
                />
              </label>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                className="min-h-11 cursor-pointer rounded-md border border-sky-400/40 px-3 disabled:opacity-40"
                disabled={!task || !running || !steerText.trim()}
                onClick={() => void sendControl("steer", steerText)}
                type="button"
              >
                Send Steer
              </button>
              <button
                className="min-h-11 cursor-pointer rounded-md border border-violet-400/40 px-3 disabled:opacity-40"
                disabled={!task || !followUpText.trim()}
                onClick={() => void sendControl("follow-up", followUpText)}
                type="button"
              >
                Queue Follow-up
              </button>
            </div>
            {hitl ? (
              <p className="text-sm text-amber-200">
                HITL: {String(hitl.payload.tool)} — {JSON.stringify(hitl.payload.arguments).slice(0, 180)}
              </p>
            ) : null}
            {error ? <p className="text-sm text-rose-300">{error}</p> : null}
          </form>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            <h3 className="text-xs uppercase tracking-wider text-slate-500">Agent 回复</h3>
            <ul className="mt-2 space-y-2 text-sm text-slate-200">
              {replies.length === 0 ? <li className="text-slate-500">等待 Agent 完成事件。</li> : null}
              {replies.map((text) => (
                <li className="rounded border border-white/10 p-2" key={text.slice(0, 40)}>
                  {text.slice(0, 800)}
                </li>
              ))}
            </ul>
            <h3 className="mt-6 text-xs uppercase tracking-wider text-slate-500">Plan</h3>
            <ul className="mt-2 space-y-1 text-sm">
              {(task?.plan ?? []).length === 0 ? <li className="text-slate-500">尚无计划</li> : null}
              {(task?.plan ?? []).map((item) => (
                <li key={item.title}>
                  {item.done ? "✓" : "○"} {item.title}
                </li>
              ))}
            </ul>
            <h3 className="mt-6 text-xs uppercase tracking-wider text-slate-500">Agent Activity</h3>
            <ol className="mt-2 space-y-2 font-mono text-xs text-slate-300">
              {events
                .filter((e) => e.type === "agent_status" || e.type === "tool_call")
                .map((event, i) => (
                  <li key={`${event.type}-${i}`}>
                    {event.type === "agent_status"
                      ? String(event.payload.role)
                      : `Tool: ${String(event.payload.tool)}`}
                  </li>
                ))}
            </ol>
          </div>
        </section>

        <section className="flex min-h-0 flex-col border-r border-white/10">
          <h2 className="px-4 py-2 text-xs uppercase tracking-wider text-slate-500">Code Workspace</h2>
          <div className="grid min-h-0 flex-1 grid-rows-2">
            <div className="grid min-h-0 grid-cols-[220px_1fr] border-b border-white/10">
              <ul className="min-h-0 overflow-y-auto px-2 py-2 text-xs">
                {files.map((file) => (
                  <li key={file}>
                    <button
                      className={`min-h-11 w-full cursor-pointer rounded px-2 text-left ${
                        file === activeFile ? "bg-white/10" : ""
                      }`}
                      onClick={() => setActiveFile(file)}
                      type="button"
                    >
                      {file}
                      {task?.changed_files.includes(file) ? " ·" : ""}
                    </button>
                  </li>
                ))}
              </ul>
              <pre className="min-h-0 overflow-auto p-4 font-mono text-xs leading-6 text-slate-200">
                {fileContent || "选择文件查看内容。"}
              </pre>
            </div>
            <DiffView diff={diff} />
          </div>
        </section>

        <section className="flex min-h-0 flex-col">
          <h2 className="px-4 py-2 text-xs uppercase tracking-wider text-slate-500">Runtime</h2>
          <div className="min-h-0 flex-1 overflow-auto px-4 pb-4">
            <div className="rounded-md border border-white/10 bg-[#12151c] p-3 text-sm">
              Role: {task?.role ?? "—"}
              <br />
              Iteration: {task?.iteration ?? 0}
              <br />
              Sandbox: {task?.sandbox.backend ?? "idle"} / {task?.sandbox.status ?? "n/a"}
              <br />
              Model: {task?.model ?? "—"}
              <br />
              Tokens: {task ? `${task.tokens.prompt} / ${task.tokens.completion}` : "0 / 0"}
            </div>
            <h3 className="mt-4 text-xs uppercase tracking-wider text-slate-500">Terminal</h3>
            <pre className="mt-2 min-h-40 overflow-auto rounded-md border border-white/10 bg-black/40 p-3 font-mono text-xs leading-6">
              {terminal || "等待 Sandbox 输出…"}
            </pre>
            <h3 className="mt-4 text-xs uppercase tracking-wider text-slate-500">Test Result</h3>
            <pre className="mt-2 overflow-auto font-mono text-xs">
              {pytestHeadline(task?.test_results || "")}
              {task?.test_results ? `\n\n${task.test_results}` : ""}
            </pre>
          </div>
        </section>
      </div>
    </div>
  );
}
