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
type Tab = "files" | "diff" | "terminal";

const STATUS_META: Record<string, { label: string; pill: string }> = {
  pending: { label: "待运行", pill: "pill-idle" },
  running: { label: "运行中", pill: "pill-running" },
  waiting_approval: { label: "等待确认", pill: "pill-running" },
  succeeded: { label: "已完成", pill: "pill-done" },
  failed: { label: "失败", pill: "pill-failed" },
  interrupted: { label: "已中断", pill: "pill-failed" },
};

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

function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return <div className="flex h-full items-center justify-center text-[14px]" style={{ color: "var(--text-3)" }}>还没有改动。任务完成后这里显示 Diff。</div>;
  }
  return (
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
  const [composerText, setComposerText] = useState("");
  const [tab, setTab] = useState<Tab>("files");
  const wsRef = useRef<WebSocket | null>(null);
  const taskIdRef = useRef("");
  const desktopRpc = isDesktopRpc();
  const scrollRef = useRef<HTMLDivElement>(null);

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

  const toolTrace = useMemo(
    () => events.filter((e) => e.type === "tool_call" || e.type === "agent_status"),
    [events],
  );

  useEffect(() => {
    taskIdRef.current = task?.task_id ?? "";
  }, [task?.task_id]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [replies.length, toolTrace.length, hitl]);

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
    setComposerText("");
  }

  async function onComposerSubmit(ev: FormEvent) {
    ev.preventDefault();
    if (!composerText.trim()) return;
    await sendControl(running ? "steer" : "follow-up", composerText);
  }

  const running = task?.status === "running";
  const statusMeta = task ? STATUS_META[task.status] ?? { label: task.status, pill: "pill-idle" } : null;
  const tests = pytestHeadline(task?.test_results || "");

  const header = (
    <header
      className="flex h-14 shrink-0 items-center justify-between px-5"
      style={{
        background: "var(--surface)",
        borderBottom: "1px solid var(--border)",
        paddingLeft: desktopRpc ? 84 : undefined,
      }}
    >
      <div className="flex items-center gap-2.5" style={{ color: "var(--accent)" }}>
        <IconMark />
        <span className="text-[15px] font-semibold" style={{ color: "var(--text)" }}>
          CoderKing
        </span>
      </div>
      <div className="flex items-center gap-4">
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
            <h1 className="text-center text-[30px] font-semibold leading-tight">
              有什么工程任务要处理？
            </h1>
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
              <div className="mt-3 flex items-center gap-3 border-t pt-3" style={{ borderColor: "var(--border)" }}>
                <label className="flex min-w-0 flex-1 items-center gap-2 text-[13.5px]" style={{ color: "var(--text-2)" }}>
                  <IconFolder />
                  <span className="sr-only">仓库路径</span>
                  <input
                    id="repo"
                    className="min-w-0 flex-1 bg-transparent text-[13.5px]"
                    style={{ border: "none", outline: "none", color: "var(--text)" }}
                    value={repository}
                    onChange={(e) => setRepository(e.target.value)}
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
                    浏览
                  </button>
                ) : null}
                <button className="btn btn-primary" disabled={busy || !prompt.trim()} type="submit">
                  {busy ? "启动中…" : "运行任务"}
                </button>
              </div>
            </form>
            {error ? (
              <p className="mt-4 text-center text-[14px]" style={{ color: "var(--err)" }}>
                {error}
              </p>
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
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[1fr_minmax(400px,42%)]">
        {/* conversation */}
        <section className="flex min-h-0 flex-col" style={{ borderRight: "1px solid var(--border)" }}>
          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            <div className="mx-auto max-w-2xl">
              <div className="chat-role">任务</div>
              <p className="text-[15px] leading-relaxed">{task.prompt}</p>

              {toolTrace.length > 0 ? (
                <div className="mt-5">
                  <div className="chat-role">代理过程</div>
                  <div className="rounded-xl px-1 py-0.5">
                    {toolTrace.map((event, i) => (
                      <div className="tool-line" key={`${event.type}-${i}`}>
                        <span
                          className={`tool-mark ${
                            event.payload.status === "ok"
                              ? "ok"
                              : event.payload.status === "error"
                                ? "error"
                                : ""
                          }`}
                        />
                        <span className="font-medium">{String(event.payload.tool ?? event.payload.role ?? "")}</span>
                        {event.payload.arguments ? (
                          <span className="truncate" style={{ color: "var(--text-3)" }}>
                            {JSON.stringify(event.payload.arguments).slice(0, 90)}
                          </span>
                        ) : null}
                        {event.payload.preview ? (
                          <span className="truncate" style={{ color: "var(--text-3)" }}>
                            {String(event.payload.preview).slice(0, 70)}
                          </span>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {hitl ? (
                <div className="card mt-5 p-4" style={{ borderLeft: "3px solid var(--accent)" }}>
                  <div className="text-[14px] font-semibold">需要确认</div>
                  <p className="mt-1 text-[14px]" style={{ color: "var(--text-2)" }}>
                    {String(hitl.payload.tool)} — {JSON.stringify(hitl.payload.arguments).slice(0, 160)}
                  </p>
                  <div className="mt-3 flex gap-2">
                    <button className="btn btn-primary" onClick={() => void act("approve")} type="button">
                      允许
                    </button>
                    <button className="btn btn-secondary" onClick={() => void act("reject")} type="button">
                      拒绝
                    </button>
                  </div>
                </div>
              ) : null}

              {replies.map((text) => (
                <div className="mt-5" key={text.slice(0, 40)}>
                  <div className="chat-role">CoderKing</div>
                  <div className="card px-4 py-3 text-[14.5px] leading-relaxed">{text.slice(0, 800)}</div>
                </div>
              ))}

              {task.status === "succeeded" || task.status === "failed" ? (
                <div className="card mt-5 flex items-center justify-between p-4">
                  <div className="text-[14px]" style={{ color: "var(--text-2)" }}>
                    {task.status === "succeeded" ? "任务完成，改动已就绪。" : "任务失败。"}
                    {tests.text ? (
                      <span style={{ color: tests.ok ? "var(--ok)" : "var(--err)" }}> 测试：{tests.text}</span>
                    ) : null}
                    <span style={{ color: "var(--text-3)" }}>
                      {" "}
                      · {task.changed_files.length} 个文件 · {task.tokens.prompt} → {task.tokens.completion} tokens
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <button className="btn btn-primary" onClick={() => void act("accept")} type="button">
                      采纳
                    </button>
                    <button className="btn btn-secondary" onClick={() => void act("rollback")} type="button">
                      回滚
                    </button>
                  </div>
                </div>
              ) : null}

              {error ? (
                <p className="mt-4 text-[14px]" style={{ color: "var(--err)" }}>
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
            <div className="card mx-auto flex max-w-2xl items-end gap-2 p-3">
              <textarea
                id="composer"
                className="min-w-0 flex-1 resize-none bg-transparent px-1 text-[14.5px] leading-relaxed"
                style={{ border: "none", outline: "none", minHeight: 40 }}
                placeholder={running ? "运行中，输入内容可改变方向…" : "继续跟进这个任务…"}
                value={composerText}
                onChange={(e) => setComposerText(e.target.value)}
              />
              {running ? (
                <button className="btn btn-secondary" onClick={() => void act("interrupt")} type="button">
                  <IconStop /> 停止
                </button>
              ) : null}
              <button
                className="btn btn-primary"
                disabled={!composerText.trim()}
                type="submit"
              >
                <IconSend /> {running ? "发送" : "跟进"}
              </button>
            </div>
          </form>
        </section>

        {/* side panel */}
        <section className="flex min-h-0 flex-col" style={{ background: "var(--surface)" }}>
          <div className="flex shrink-0 items-center gap-5 px-5" style={{ borderBottom: "1px solid var(--border)" }}>
            {(["files", "diff", "terminal"] as Tab[]).map((t) => (
              <button
                className={`tab ${tab === t ? "tab-active" : ""}`}
                key={t}
                onClick={() => setTab(t)}
                type="button"
              >
                {t === "files" ? "文件" : t === "diff" ? "Diff" : "终端"}
              </button>
            ))}
            <span className="ml-auto text-[13px]" style={{ color: "var(--text-3)" }}>
              {files.length ? `${files.length} 个文件` : ""}
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

          {tab === "diff" ? (
            <div className="flex min-h-0 flex-1 flex-col p-4">
              <DiffView diff={diff} />
            </div>
          ) : null}

          {tab === "terminal" ? (
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
              <pre className="code-block min-h-0 flex-1">{terminal || "等待沙箱输出…"}</pre>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
