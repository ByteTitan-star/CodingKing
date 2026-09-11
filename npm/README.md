# codeking (npm)

`npm install -g codeking` — the CodeKing coding agent CLI, distributed via npm
exactly like Claude Code.

## How it works

The npm package is a thin launcher. On `postinstall` it provisions a private
Python venv at `~/.codeking/venv` (Python 3.12+ required, or `uv`) and pip
installs the `coderking` Python distribution into it. The `codeking` / `coderking`
binaries then spawn that interpreter — no PATH pollution, no activation needed.

```
npm install -g codeking
codeking            # straight into the interactive REPL (little boy · CNU splash)
codeking run "…"    # one-shot task
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `CODEKING_PYTHON` | Pin the interpreter used to create the venv |
| `CODEKING_SOURCE` | Install from a local path / git URL instead of PyPI (dev) |
| `CODEKING_SKIP_INSTALL` | Skip provisioning (offline reinstall of the wrapper only) |
| `PIP_INDEX_URL` | Standard pip mirror passthrough for restricted networks |

Model config lives in `~/.coderking/.env` (global) or a project `.env`.

## Publishing (maintainers)

```bash
cd npm
npm login
npm publish
```

Bump `version` here in lockstep with `pyproject.toml`, and make sure the
matching `coderking` version is already on PyPI (the installer falls back to
the GitHub source if it isn't).
