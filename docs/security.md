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

## Verification

```bash
python -m pytest -q tests/sandbox/test_credential_isolation.py
```

CI asserts:

- Scrubbed env has no secret prefixes / `sk-` markers
- CoW clone omits secret paths
- Docker `build_args` contain no host API keys
- Local sandbox `printenv`-style probes do not leak keys
