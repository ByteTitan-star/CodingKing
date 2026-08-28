import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { RpcBridge, resolveCoderkingRpcArgs } from "./rpc-bridge.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEV_URL = process.env.CODERKING_DESKTOP_URL || "http://localhost:5188";
const useDist = process.argv.includes("--dist") || app.isPackaged;

let mainWindow = null;
let rpcBridge = null;
let workspaceDir = null;

function forwardEvent(record) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("agent:event", record);
  }
}

async function ensureBridge(dir) {
  const next = path.resolve(dir);
  if (rpcBridge && workspaceDir === next) return rpcBridge;
  stopBridge();
  workspaceDir = next;
  const { command, args } = resolveCoderkingRpcArgs(next);
  rpcBridge = new RpcBridge({ command, args, cwd: next });
  rpcBridge.on("event", forwardEvent);
  rpcBridge.on("stderr", (text) => {
    console.error("[coderking-rpc]", text.trim());
  });
  rpcBridge.on("exit", () => {
    rpcBridge = null;
    workspaceDir = null;
  });
  return rpcBridge;
}

function stopBridge() {
  if (!rpcBridge) return;
  rpcBridge.removeAllListeners();
  rpcBridge.kill();
  rpcBridge = null;
  workspaceDir = null;
}

function requireBridge() {
  if (!rpcBridge) {
    throw new Error("RPC bridge not started; set workspace first");
  }
  return rpcBridge;
}

function asTaskParams(params) {
  const taskId = String(params?.task_id ?? "").trim();
  if (!taskId) throw new Error("task_id is required");
  return taskId;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: "#020617",
    title: "CoderKing",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  if (useDist) {
    void mainWindow.loadFile(path.join(__dirname, "..", "web", "dist", "index.html"));
  } else {
    void mainWindow.loadURL(DEV_URL);
  }

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });
}

app.whenReady().then(() => {
  ipcMain.handle("dialog:openDirectory", async () => {
    const result = await dialog.showOpenDialog({
      properties: ["openDirectory"],
    });
    if (result.canceled || !result.filePaths[0]) return null;
    return result.filePaths[0];
  });

  ipcMain.handle("agent:setWorkspace", async (_event, dir) => {
    if (typeof dir !== "string" || !dir.trim()) {
      throw new Error("workspace must be a non-empty string");
    }
    await ensureBridge(dir.trim());
    return { workspace: workspaceDir };
  });

  ipcMain.handle("agent:prompt", async (_event, params) => {
    const bridge = requireBridge();
    const text = String(params?.text ?? "").trim();
    if (!text) throw new Error("text is required");
    return bridge.call("agent.prompt", {
      text,
      auto_approve: Boolean(params?.auto_approve),
      test_command: params?.test_command ?? null,
    });
  });

  ipcMain.handle("agent:steer", async (_event, params) => {
    const bridge = requireBridge();
    return bridge.call("agent.steer", {
      task_id: asTaskParams(params),
      content: String(params?.content ?? ""),
    });
  });

  ipcMain.handle("agent:followUp", async (_event, params) => {
    const bridge = requireBridge();
    return bridge.call("agent.follow_up", {
      task_id: asTaskParams(params),
      content: String(params?.content ?? ""),
    });
  });

  ipcMain.handle("agent:abort", async (_event, params) => {
    const bridge = requireBridge();
    return bridge.call("agent.abort", { task_id: asTaskParams(params) });
  });

  ipcMain.handle("agent:getTask", async (_event, params) => {
    const bridge = requireBridge();
    return bridge.call("agent.get_task", { task_id: asTaskParams(params) });
  });

  ipcMain.handle("agent:diff", async (_event, params) => {
    const bridge = requireBridge();
    return bridge.call("agent.diff", { task_id: asTaskParams(params) });
  });

  ipcMain.handle("agent:tree", async (_event, params) => {
    const bridge = requireBridge();
    return bridge.call("agent.tree", { task_id: asTaskParams(params) });
  });

  ipcMain.handle("agent:readFile", async (_event, params) => {
    const bridge = requireBridge();
    const rel = String(params?.path ?? "").trim();
    if (!rel) throw new Error("path is required");
    return bridge.call("agent.read_file", {
      task_id: asTaskParams(params),
      path: rel,
    });
  });

  ipcMain.handle("agent:approve", async (_event, params) => {
    const bridge = requireBridge();
    return bridge.call("agent.approve", { task_id: asTaskParams(params) });
  });

  ipcMain.handle("agent:reject", async (_event, params) => {
    const bridge = requireBridge();
    return bridge.call("agent.reject", { task_id: asTaskParams(params) });
  });

  ipcMain.handle("agent:rollback", async (_event, params) => {
    const bridge = requireBridge();
    return bridge.call("agent.rollback", { task_id: asTaskParams(params) });
  });

  ipcMain.handle("agent:accept", async (_event, params) => {
    const bridge = requireBridge();
    return bridge.call("agent.accept", { task_id: asTaskParams(params) });
  });

  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("before-quit", () => {
  stopBridge();
});

app.on("window-all-closed", () => {
  stopBridge();
  if (process.platform !== "darwin") app.quit();
});
