// install.js — provisions a private venv for the CodeKing CLI on postinstall.
//
// Resolution order for the Python runtime:
//   1. CODEKING_PYTHON env (absolute path)
//   2. python3.12 / python3.13 / python3 on PATH (must report >= 3.12)
//   3. `uv` on PATH (uv venv --python 3.12 downloads a managed CPython)
//
// Package source resolution:
//   1. CODEKING_SOURCE env (e.g. a local path or git URL, for dev)
//   2. coderking==<version> from PyPI (the Python distribution name)
//   3. git+https://github.com/ByteTitan-star/CodingKing.git (PyPI fallback)
"use strict";

const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const VERSION = require("./package.json").version;
const HOME = os.homedir();
const VENV_DIR = path.join(HOME, ".codeking", "venv");
const IS_WIN = process.platform === "win32";
const BIN = IS_WIN ? "Scripts" : "bin";

function run(cmd, args, opts = {}) {
  return execFileSync(cmd, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], ...opts });
}

function tryRun(cmd, args) {
  try {
    return run(cmd, args);
  } catch {
    return null;
  }
}

function findPython() {
  if (process.env.CODEKING_PYTHON) return process.env.CODEKING_PYTHON;
  for (const candidate of ["python3.12", "python3.13", "python3", "python"]) {
    const out = tryRun(candidate, ["-c", "import sys; print(sys.version_info[0]*100+sys.version_info[1])"]);
    if (out && Number(out.trim()) >= 312) return candidate;
  }
  return null;
}

function venvPython() {
  return path.join(VENV_DIR, BIN, IS_WIN ? "python.exe" : "python");
}

function venvExists() {
  return fs.existsSync(venvPython());
}

function createVenv() {
  fs.mkdirSync(path.dirname(VENV_DIR), { recursive: true });
  const python = findPython();
  if (python) {
    run(python, ["-m", "venv", VENV_DIR], { stdio: "inherit" });
    return;
  }
  const uv = tryRun("uv", ["--version"]);
  if (uv) {
    run("uv", ["venv", VENV_DIR, "--python", "3.12"], { stdio: "inherit" });
    return;
  }
  console.error(
    "\nCodeKing needs Python 3.12+ (or uv) to install its runtime.\n" +
      "  macOS:  brew install python@3.12\n" +
      "  Linux:  use your package manager or https://uv.sh\n" +
      "  Then re-run: npm install -g codeking\n" +
      "  Or point to an interpreter: CODEKING_PYTHON=/path/to/python3.12 npm install -g codeking\n",
  );
  process.exit(1);
}

function pipArgs() {
  const source =
    process.env.CODEKING_SOURCE ||
    `coderking==${VERSION}`;
  const args = ["-m", "pip", "install", "--quiet", "--upgrade", source];
  if (!process.env.CODEKING_SOURCE) {
    // PyPI primary; fall back to the GitHub source if PyPI misses.
    return [args, ["-m", "pip", "install", "--quiet", "--upgrade", "git+https://github.com/ByteTitan-star/CodingKing.git"]];
  }
  return [args];
}

function main() {
  if (process.env.CODEKING_SKIP_INSTALL) return;
  try {
    if (!venvExists()) {
      console.log("codeking: creating runtime venv at " + VENV_DIR);
      createVenv();
    }
    const py = venvPython();
    let installed = false;
    let lastError = null;
    for (const args of pipArgs()) {
      try {
        execFileSync(py, args, { stdio: "inherit" });
        installed = true;
        break;
      } catch (err) {
        lastError = err;
      }
    }
    if (!installed) {
      console.error("\ncodeking: failed to install the Python package.");
      console.error(String(lastError && lastError.message ? lastError.message : lastError));
      console.error(
        "Check the network (or set PIP_INDEX_URL to a mirror), or install from source:\n" +
          "  CODEKING_SOURCE=git+https://github.com/ByteTitan-star/CodingKing.git npm install -g codeking\n",
      );
      process.exit(1);
    }
    console.log(`codeking ${VERSION}: ready — run \`codeking\` to start.`);
  } catch (err) {
    // Never leave the user without a hint.
    console.error("codeking: install step failed:", err.message);
    process.exit(1);
  }
}

if (require.main === module) main();

module.exports = { main, venvPython, venvExists };
