type AgentEvent = { type: string; payload: Record<string, unknown> };

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
  errors: string[];
  events?: AgentEvent[];
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
): Promise<{ task_id: string }> {
  const api = bridge();
  if (!api?.setWorkspace || !api.prompt) throw new Error("desktop RPC unavailable");
  await api.setWorkspace(repository);
  return api.prompt({ text: prompt, auto_approve: autoApprove });
}

export function subscribeEvents(onEvent: (event: AgentEvent) => void): () => void {
  const api = bridge();
  if (!api?.onEvent) return () => undefined;
  return api.onEvent((record) => {
    onEvent({
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

export async function postTaskAction(
  taskId: string,
  action: "approve" | "reject" | "rollback" | "accept" | "interrupt" | "steer" | "follow-up",
  content?: string,
): Promise<void> {
  const api = bridge();
  if (!api) throw new Error("desktop RPC unavailable");
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
}

export async function pickDirectory(): Promise<string | null> {
  const api = bridge();
  if (!api?.openDirectory) return null;
  return api.openDirectory();
}
