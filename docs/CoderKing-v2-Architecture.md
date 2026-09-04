# CoderKing v2 Architecture

Aligned with the [Pi](https://github.com/earendil-works/pi) four-layer packaging. This document is the contract for the coding-agent runtime (pure loop — **no multi-role workflow**).

## Layers

| Layer | Package | Responsibility | Forbidden deps |
|-------|---------|----------------|----------------|
| L0 | `coderking_llm` | Multi-provider LLM adapter, streaming, retry, token stats | `coderking_agent_core`, `coderking_coding_agent`, `coderking_transport`, workspace/sandbox/tools |
| L1 | `coderking_agent_core` | Pure Agent Loop, Steering/Follow-up, EventStream, hooks | `coderking_coding_agent`, `coderking_transport`, sandbox/git/workspace |
| L2 | `coderking_coding_agent` | Read/Write/Edit/Bash, SessionRepo, compression, Extensions | FastAPI, Electron, CLI TUI rendering |
| L3 | `coderking_transport` | CLI/TUI, HTTP/SSE, RPC stdio, Desktop bridge | Must not rewrite messages; call L1/L2 APIs only |
| Facade | `coderking` (`src/coderking`) | Compatibility layer and CLI entry; thin re-exports | No new business logic here |

Dependency direction (downward only):

```text
transport (L3)
    → coding_agent (L2)
        → agent_core (L1)
            → llm (L0)
```

## Runtime model

CoderKing is a **single coding agent**:

- One L1 loop (`Perceive → Decide → Act → Observe`)
- Four tools: `read` / `write` / `edit` / `bash`
- Verification is prompt-guided (run checks via `bash`; optional `--test` soft hint)
- **No** Planner/Coding/Execution/Reviewer/Repair role FSM
- **No** fixed workflow stages or meta-tools (`submit_plan`, `finish_task`, …)

## Directory

```text
packages/
  coderking_llm/src/coderking_llm/
  coderking_agent_core/src/coderking_agent_core/
  coderking_coding_agent/src/coderking_coding_agent/
  coderking_transport/src/coderking_transport/
src/coderking/          # thin facade + CLI entry
scripts/check_layer_deps.py
```

## Boundary enforcement

`scripts/check_layer_deps.py` AST-scans `packages/*/src` imports; violations fail CI after Ruff.

## Acceptance

- [x] Four layer packages installable via `pip install -e ".[dev]"`
- [x] `python scripts/check_layer_deps.py` exit 0
- [x] Non-docker pytest green
- [x] No cyclic deps
- [x] Facade wires `AtomicL1Runtime` only (no SWE harness branch)
