/// <reference types="vite/client" />

interface CoderKingDesktopBridge {
  useRpc?: boolean;
  apiBase?: string;
  openDirectory?: () => Promise<string | null>;
  setWorkspace?: (dir: string) => Promise<{ workspace: string }>;
  prompt?: (params: {
    text: string;
    auto_approve?: boolean;
    test_command?: string | null;
    session_id?: string | null;
  }) => Promise<{ task_id: string }>;
  steer?: (params: { task_id: string; content: string }) => Promise<{ ok: boolean }>;
  followUp?: (params: { task_id: string; content: string }) => Promise<{ ok: boolean }>;
  abort?: (params: { task_id: string }) => Promise<{ ok: boolean }>;
  getTask?: (params: { task_id: string }) => Promise<Record<string, unknown>>;
  getDiff?: (params: { task_id: string }) => Promise<{ diff: string }>;
  getTree?: (params: { task_id: string }) => Promise<{ files: string[] }>;
  readFile?: (params: { task_id: string; path: string }) => Promise<{ content: string }>;
  approve?: (params: { task_id: string }) => Promise<{ ok: boolean }>;
  reject?: (params: { task_id: string }) => Promise<{ ok: boolean }>;
  rollback?: (params: { task_id: string }) => Promise<{ ok: boolean }>;
  accept?: (params: { task_id: string }) => Promise<{ ok: boolean }>;
  retry?: (params: {
    task_id: string;
    text?: string | null;
    auto_approve?: boolean;
    skills?: string[];
  }) => Promise<{ task_id: string; parent_run_id: string }>;
  getCheckpoints?: (params: {
    task_id: string;
  }) => Promise<{ checkpoints?: Record<string, unknown>[] }>;
  rollbackCheckpoint?: (params: {
    task_id: string;
    checkpoint_id: string;
  }) => Promise<{ ok: boolean }>;
  listSessions?: (params: {
    limit?: number;
  }) => Promise<{ sessions?: Record<string, unknown>[] }>;
  loadSession?: (params: { session_id: string }) => Promise<{
    session_id: string;
    head_id?: string | null;
    messages?: { role: string; content: unknown }[];
    state?: Record<string, unknown>;
  }>;
  getConfig?: () => Promise<{
    model: string;
    workspace: string;
    reasoning_effort?: string;
  }>;
  updateConfig?: (params: {
    model?: string;
    reasoning_effort?: string;
  }) => Promise<{ ok: boolean; model: string; reasoning_effort?: string }>;
  onEvent?: (
    callback: (record: {
      id?: string;
      type: string;
      payload?: Record<string, unknown>;
    }) => void,
  ) => () => void;
}

interface Window {
  coderkingDesktop?: CoderKingDesktopBridge;
}
