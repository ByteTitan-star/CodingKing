import { EventEmitter } from "node:events";
import { spawn } from "node:child_process";
import readline from "node:readline";

function asString(value) {
  return typeof value === "string" ? value : "";
}

/** Resolve coderking RPC spawn argv without shell interpolation. */
export function resolveCoderkingRpcArgs(workspace) {
  const dir = asString(workspace).trim();
  if (!dir) {
    throw new Error("workspace is required");
  }
  const bin = asString(process.env.CODERKING_BIN).trim();
  if (bin) {
    return { command: bin, args: ["rpc", "--workspace", dir] };
  }
  const py = asString(process.env.CODERKING_PYTHON).trim() || "python";
  return { command: py, args: ["-m", "coderking", "rpc", "--workspace", dir] };
}

export class RpcBridge extends EventEmitter {
  constructor({ command, args, cwd = undefined }) {
    super();
    this._nextId = 1;
    this._pending = new Map();
    this._closed = false;
    this._child = spawn(command, args, {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
      shell: false,
      windowsHide: true,
    });
    this._rl = readline.createInterface({ input: this._child.stdout });
    this._rl.on("line", (line) => this._onLine(line));
    this._child.on("error", (err) => this.emit("error", err));
    this._child.on("exit", (code, signal) => {
      this._closed = true;
      for (const pending of this._pending.values()) {
        pending.reject(new Error(`rpc process exited (${code ?? signal ?? "unknown"})`));
      }
      this._pending.clear();
      this.emit("exit", { code, signal });
    });
    this._child.stderr.on("data", (chunk) => {
      this.emit("stderr", chunk.toString("utf8"));
    });
  }

  _onLine(line) {
    const trimmed = line.trim();
    if (!trimmed) return;
    let message;
    try {
      message = JSON.parse(trimmed);
    } catch {
      this.emit("stderr", `invalid json: ${trimmed.slice(0, 200)}`);
      return;
    }
    if (message.method === "agent.event") {
      this.emit("event", message.params ?? {});
      return;
    }
    if (message.id === undefined || message.id === null) return;
    const pending = this._pending.get(message.id);
    if (!pending) return;
    this._pending.delete(message.id);
    if (message.error) {
      pending.reject(new Error(String(message.error.message ?? "rpc error")));
      return;
    }
    pending.resolve(message.result ?? {});
  }

  call(method, params = {}) {
    if (this._closed) {
      return Promise.reject(new Error("rpc process is not running"));
    }
    const id = this._nextId++;
    const payload = `${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`;
    return new Promise((resolve, reject) => {
      this._pending.set(id, { resolve, reject });
      this._child.stdin.write(payload, (err) => {
        if (err) {
          this._pending.delete(id);
          reject(err);
        }
      });
    });
  }

  kill() {
    if (this._closed) return;
    this._closed = true;
    this._rl.close();
    this._child.kill("SIGTERM");
    setTimeout(() => {
      if (!this._child.killed) this._child.kill("SIGKILL");
    }, 2000).unref();
  }
}
