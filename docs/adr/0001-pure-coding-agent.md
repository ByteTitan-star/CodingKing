# ADR 0001: Pure Coding Agent (no role workflow)

- Status: Accepted
- Date: 2026-09-04

## Context

CoderKing previously shipped an optional five-role SWE harness
(Planner → Coding → Execution → Reviewer → Repair) with meta-tools and hard
routing. That path behaved like a fixed workflow and conflicted with the
Pi-aligned goal: a flexible coding agent driven by a pure tool-use loop.

## Decision

1. CoderKing is **only** a coding agent runtime: one L1 loop + four tools
   (`read` / `write` / `edit` / `bash`).
2. The SWE role harness, meta-tools (`submit_plan`, `finish_task`, …), role
   tool allowlists, and `extension=swe|atomic` switches are **removed**.
3. Post-edit verification is **prompt-guided** (run checks via `bash`), with an
   optional `--test` soft hint. No hard review stage / workflow gate.
4. Design docs and product copy must describe the pure loop, not multi-role
   pipelines.

## Consequences

- Simpler mental model for interviews and contributors.
- Eval / scripted tests use atomic tools only.
- Legacy SWE-specific tests and prompts are deleted.
- Session JSON may still carry a display `role` field for compatibility, but it
  is not a workflow stage machine.
