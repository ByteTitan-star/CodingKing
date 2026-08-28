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
