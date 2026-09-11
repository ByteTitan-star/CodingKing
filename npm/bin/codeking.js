#!/usr/bin/env node
// bin/codeking.js — global launcher. Spawns the venv-installed CLI with
// inherited stdio so the interactive REPL, colors and signals all work.
"use strict";

const { spawn } = require("node:child_process");
const os = require("node:os");
const path = require("node:path");

const IS_WIN = process.platform === "win32";
const VENV_DIR = path.join(os.homedir(), ".codeking", "venv");
const VENV_PYTHON = path.join(VENV_DIR, IS_WIN ? "Scripts" : "bin", IS_WIN ? "python.exe" : "python");

const fs = require("node:fs");

if (!fs.existsSync(VENV_PYTHON)) {
  // The venv is gone (or install was skipped) — provision it on demand.
  require("../install.js").main();
  if (!fs.existsSync(VENV_PYTHON)) {
    console.error("codeking: runtime not installed. Re-run `npm install -g codeking`.");
    process.exit(1);
  }
}

const child = spawn(VENV_PYTHON, ["-m", "coderking", ...process.argv.slice(2)], {
  stdio: "inherit",
  env: process.env,
  windowsHide: true,
});

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    child.kill(sig);
  });
}

child.on("error", (err) => {
  console.error("codeking: failed to launch:", err.message);
  process.exit(1);
});

child.on("close", (code) => {
  process.exit(code === null ? 130 : code);
});
