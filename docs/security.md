# Security — Credential Isolation

CoderKing keeps LLM API keys and other host secrets **out of the sandbox**.
Only the host agent process may call model providers; tool and bash executions
run with a scrubbed environment and a secret-aware workspace clone.

## Principles

1. **Host-only credentials** — `CODERKING_*`, `OPENAI_*`, `ANTHROPIC_*`, and
   similar provider keys stay on the host. Sandbox children never inherit them.
2. **Scrubbed env** — Local / background jobs inherit the host environment with
   secret names stripped (`coderking.sandbox.credentials.scrub_env`). Docker
   containers do **not** inherit host env; they only get `CODERKING_SANDBOX=1`
   plus optional explicit allowlisted extras.
3. **Secret paths excluded from CoW / clones** — `.env`, `.env.*`, `*credentials*`,
   `*secret*`, `*.pem`, `*.key`, `.git/config`, and `.coderking/` are not copied
   into overlay workspaces.
4. **LLM calls stay on the host** — tool and bash processes must not hold API keys.

## What runs where

| Concern | Host | Sandbox |
|--------|------|---------|
| LLM API calls | Yes | No |
| Tool / bash execution | Orchestration only | Yes (scrubbed) |
| `.env` / API key files | May exist | Not cloned into CoW |
| Background jobs (`JobManager`) | — | Scrubbed env |

## Configuration notes

- Set provider keys via host env (e.g. `CODERKING_OPENAI_API_KEY`) or config
  used solely by the host process.
- Enable CoW overlays with `CODERKING_SANDBOX_COW` / `settings.sandbox_cow` so
  tool writes stay in `.coderking/cow/{task}/work` until promote.
- Docker network defaults to off (`sandbox_network=false`); open only when needed.

## Network policy

| Mode | Behavior |
|------|----------|
| `none` (default) | Docker `--network none` (no egress) |
| `full` | Default bridge (legacy `sandbox_network=true`) |
| `restricted` | Default bridge + host allowlist proxy (`HTTP(S)_PROXY`) + `--dns 127.0.0.1` |

Configure via `CODERKING_SANDBOX_NETWORK_MODE` / `sandbox_network_mode` and
`CODERKING_SANDBOX_ALLOW_HOSTS` (comma-separated). Misconfigured `restricted`
without hosts raises a clear `ValueError`.

### Restricted mode is proxy best-effort

`restricted` does **not** enforce container-boundary egress isolation (it does
not use `--network none`). It:

1. Starts a host-side allowlist HTTP proxy (Basic auth) and injects `HTTP(S)_PROXY`
2. Points container DNS at `127.0.0.1` so hostname lookups that skip the proxy fail
3. Still allows processes that ignore the proxy **and** use raw IP literals to reach
   the public internet on the default Docker bridge

Treat `restricted` as a cooperation layer for package managers / HTTP clients that
honor proxy env vars—not as a hard network jail. Prefer `none` when egress is not
required.

## Micro-VM backend

Set `CODERKING_SANDBOX_MODE=microvm` to use the Micro-VM sandbox:

| Provider (`CODERKING_SANDBOX_MICROVM_PROVIDER`) | Role |
|-----------------------------------------------|------|
| `mock` (default) | Docker sealed mounts — host `/etc/passwd` is not visible |
| `e2b` | Hosted Micro-VM via E2B (`CODERKING_E2B_API_KEY`) |
| `firecracker` | Phase 4b stub (raises clear `NotImplementedError`) |

LLM credentials stay on the host; Micro-VM sessions only see workspace mounts
and scrubbed/marker env vars.

## Verification

```bash
python -m pytest -q tests/sandbox/test_credential_isolation.py
python -m pytest -q tests/sandbox/test_network_policy.py
python -m pytest -q tests/sandbox/test_microvm.py -m "not docker"
```

CI asserts:

- Scrubbed env has no secret prefixes / `sk-` markers
- CoW clone omits secret paths
- Docker `build_args` contain no host API keys
- Local sandbox `printenv`-style probes do not leak keys
