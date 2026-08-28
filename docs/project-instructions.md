# Project Instructions (AGENTS.md / SYSTEM.md)

CoderKing loads optional project instructions on the **first turn only** of a new session. This keeps the core system prompt small while still giving the agent repo-specific guidance.

## Search order

1. `AGENTS.md` (workspace root)
2. `SYSTEM.md` (workspace root)
3. `.coderking/AGENTS.md`

## Limits

- Maximum **8 KB** per file; larger files are truncated and a warning event is emitted.
- Instructions are injected once per session as a `user` message wrapped in:

```xml
<project_instructions source="AGENTS.md">
...
</project_instructions>
```

## CLI

```bash
coderking init
```

Creates `.coderking/config.yaml` and an `AGENTS.md` template when missing.

## Web API

```http
GET /api/workspace/project-instructions?root=.
```

Returns `{ loaded, source, hash, truncated, bytes }` for the settings page.

## Implementation

- Loader: `coderking_coding_agent.context.project_docs.ProjectInstructionsLoader`
- Injection: L2 hook wired from `AgentRuntime` on first turn only
