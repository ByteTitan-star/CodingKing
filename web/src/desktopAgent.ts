import { apiUrl } from "./apiBase";

type AgentEvent = { id?: string; type: string; payload: Record<string, unknown> };

export type TaskView = {
  task_id: string;
  prompt: string;
  status: string;
  role: string;
  iteration: number;
  plan: { title: string; done: boolean }[];
  changed_files: string[];
  test_results: string;
  model?: string;
  sandbox: { backend: string; status: string };
  tokens: { prompt: number; completion: number };
  context?: {
    estimated_tokens: number;
    compression_count: number;
    micro_compaction_count: number;
  };
  checkpoints?: { count: number; latest_id?: string };
  errors: string[];
  timing?: { created_at?: string; updated_at?: string; finished_at?: string };
  session_id?: string;
  events?: AgentEvent[];
};

export type CheckpointView = {
  checkpoint_id: string;
  status: string;
  tool: string;
  path: string;
  recoverable: boolean;
  reason?: string | null;
};

export type SessionMeta = {
  session_id: string;
  updated_at: string;
  prompt: string;
  nodes: number;
  tokens: { prompt: number; completion: number };
  running?: boolean;
};

function bridge() {
  const desktop = window.coderkingDesktop;
  if (!desktop?.useRpc) return null;
  return desktop;
}

export function isDesktopRpc(): boolean {
  return Boolean(bridge());
}

export async function setWorkspace(repository: string): Promise<void> {
  const api = bridge();
  if (!api?.setWorkspace) throw new Error("desktop RPC unavailable");
  await api.setWorkspace(repository);
}

export async function startTask(
  prompt: string,
  repository: string,
  autoApprove: boolean,
  sessionId?: string | null,
): Promise<{ task_id: string }> {
  const api = bridge();
  if (!api?.setWorkspace || !api.prompt) throw new Error("desktop RPC unavailable");
  await api.setWorkspace(repository);
  return api.prompt({
    text: prompt,
    auto_approve: autoApprove,
    session_id: sessionId ?? null,
  });
}

export function subscribeEvents(onEvent: (event: AgentEvent) => void): () => void {
  const api = bridge();
  if (!api?.onEvent) return () => undefined;
  return api.onEvent((record) => {
    onEvent({
      id: typeof record.id === "string" ? record.id : undefined,
      type: String(record.type ?? ""),
      payload: (record.payload as Record<string, unknown>) ?? {},
    });
  });
}

export async function fetchTask(taskId: string): Promise<TaskView> {
  const api = bridge();
  if (!api?.getTask) throw new Error("desktop RPC unavailable");
  return api.getTask({ task_id: taskId }) as Promise<TaskView>;
}

export async function fetchDiff(taskId: string): Promise<string> {
  const api = bridge();
  if (!api?.getDiff) throw new Error("desktop RPC unavailable");
  const data = (await api.getDiff({ task_id: taskId })) as { diff: string };
  return data.diff ?? "";
}

export async function fetchTree(taskId: string): Promise<string[]> {
  const api = bridge();
  if (!api?.getTree) throw new Error("desktop RPC unavailable");
  const data = (await api.getTree({ task_id: taskId })) as { files: string[] };
  return data.files ?? [];
}

export async function fetchFile(taskId: string, rel: string): Promise<string> {
  const api = bridge();
  if (!api?.readFile) throw new Error("desktop RPC unavailable");
  const data = (await api.readFile({ task_id: taskId, path: rel })) as { content: string };
  return data.content ?? "";
}

export async function fetchCheckpoints(taskId: string): Promise<CheckpointView[]> {
  const api = bridge();
  if (api?.getCheckpoints) {
    const data = (await api.getCheckpoints({ task_id: taskId })) as {
      checkpoints: CheckpointView[];
    };
    return data.checkpoints ?? [];
  }
  return [];
}

export async function rollbackCheckpoint(taskId: string, checkpointId: string): Promise<void> {
  const api = bridge();
  if (!api?.rollbackCheckpoint) throw new Error("desktop RPC unavailable");
  await api.rollbackCheckpoint({ task_id: taskId, checkpoint_id: checkpointId });
}

export async function listSessions(limit = 50): Promise<SessionMeta[] | null> {
  const api = bridge();
  if (!api?.listSessions) return null;
  const data = (await api.listSessions({ limit })) as { sessions: SessionMeta[] };
  return data.sessions ?? [];
}

export type LoadedSession = {
  session_id: string;
  messages: { role: string; text: string }[];
};

export async function loadSession(sessionId: string): Promise<LoadedSession | null> {
  const api = bridge();
  if (!api?.loadSession) return null;
  const data = await api.loadSession({ session_id: sessionId });
  const messages = (data.messages ?? []).map((msg) => ({
    role: msg.role,
    text: typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content ?? ""),
  }));
  return { session_id: sessionId, messages };
}

export type AppConfig = {
  model: string;
  workspace: string;
  reasoning_effort?: string;
};

export async function getConfig(): Promise<AppConfig | null> {
  const api = bridge();
  if (!api?.getConfig) return null;
  return api.getConfig();
}

export async function updateConfig(update: {
  model?: string;
  reasoning_effort?: string;
}): Promise<boolean> {
  const api = bridge();
  if (!api?.updateConfig) return false;
  await api.updateConfig(update);
  return true;
}

export async function retryTask(
  taskId: string,
  text: string | null,
): Promise<{ task_id: string; parent_run_id: string }> {
  const api = bridge();
  if (api?.retry) return api.retry({ task_id: taskId, text });
  const res = await fetch(apiUrl(`/api/tasks/${taskId}/retry`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: text ?? "" }),
  });
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as { task_id: string; parent_run_id: string };
}

export async function postTaskAction(
  taskId: string,
  action: "approve" | "reject" | "rollback" | "accept" | "interrupt" | "steer" | "follow-up",
  content?: string,
): Promise<void> {
  const api = bridge();
  if (api) {
    const params = { task_id: taskId };
    switch (action) {
      case "approve":
        await api.approve?.(params);
        break;
      case "reject":
        await api.reject?.(params);
        break;
      case "rollback":
        await api.rollback?.(params);
        break;
      case "accept":
        await api.accept?.(params);
        break;
      case "interrupt":
        await api.abort?.(params);
        break;
      case "steer":
        await api.steer?.({ ...params, content: content ?? "" });
        break;
      case "follow-up":
        await api.followUp?.({ ...params, content: content ?? "" });
        break;
      default:
        break;
    }
    return;
  }
  await fetch(apiUrl(`/api/tasks/${taskId}/${action}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: content !== undefined ? JSON.stringify({ content }) : undefined,
  });
}

export async function pickDirectory(): Promise<string | null> {
  const api = bridge();
  if (!api?.openDirectory) return null;
  return api.openDirectory();
}
