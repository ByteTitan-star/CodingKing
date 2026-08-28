import assert from "node:assert/strict";
import test from "node:test";
import { RpcBridge, resolveCoderkingRpcArgs } from "./rpc-bridge.mjs";

test("resolveCoderkingRpcArgs uses argv without shell", () => {
  const prevBin = process.env.CODERKING_BIN;
  const prevPy = process.env.CODERKING_PYTHON;
  delete process.env.CODERKING_BIN;
  delete process.env.CODERKING_PYTHON;
  const resolved = resolveCoderkingRpcArgs("/tmp/workspace");
  assert.equal(resolved.command, "python");
  assert.deepEqual(resolved.args, ["-m", "coderking", "rpc", "--workspace", "/tmp/workspace"]);
  if (prevBin) process.env.CODERKING_BIN = prevBin;
  if (prevPy) process.env.CODERKING_PYTHON = prevPy;
});

test("resolveCoderkingRpcArgs honors CODERKING_BIN", () => {
  const prev = process.env.CODERKING_BIN;
  process.env.CODERKING_BIN = "/usr/local/bin/coderking";
  const resolved = resolveCoderkingRpcArgs("/repo");
  assert.equal(resolved.command, "/usr/local/bin/coderking");
  assert.deepEqual(resolved.args, ["rpc", "--workspace", "/repo"]);
  if (prev) process.env.CODERKING_BIN = prev;
  else delete process.env.CODERKING_BIN;
});

test("RpcBridge forwards agent.event notifications", () => {
  const bridge = new RpcBridge({
    command: process.execPath,
    args: ["-e", "setInterval(()=>{}, 1000)"],
  });
  const events = [];
  bridge.on("event", (record) => events.push(record));
  bridge._onLine(
    JSON.stringify({
      jsonrpc: "2.0",
      method: "agent.event",
      params: { id: "t-000001", type: "done", payload: { ok: true } },
    }),
  );
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "done");
  bridge.kill();
});

test("RpcBridge resolves JSON-RPC responses", async () => {
  const bridge = new RpcBridge({
    command: process.execPath,
    args: ["-e", "setInterval(()=>{}, 1000)"],
  });
  setImmediate(() => {
    bridge._onLine(JSON.stringify({ jsonrpc: "2.0", id: 1, result: { task_id: "abc" } }));
  });
  const result = await bridge.call("agent.prompt", { text: "hi" });
  assert.equal(result.task_id, "abc");
  bridge.kill();
});
