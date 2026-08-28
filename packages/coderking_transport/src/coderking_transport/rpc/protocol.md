# RPC JSONL over Stdio

CoderKing exposes a Pi-style JSON-RPC 2.0 line protocol on stdin/stdout for Desktop and automation clients.

## Transport

- **stdin**: client requests (one JSON object per line)
- **stdout**: server responses and event notifications (one JSON object per line, flushed immediately)
- **stderr**: structured logs only (never protocol frames)

## Request

```json
{"jsonrpc":"2.0","id":1,"method":"agent.prompt","params":{"text":"fix the add bug"}}
```

## Response

```json
{"jsonrpc":"2.0","id":1,"result":{"task_id":"abc123"}}
```

## Error

```json
{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Method not found"}}
```

## Event notification (no `id`)

```json
{"jsonrpc":"2.0","method":"agent.event","params":{"id":"abc123-000001","type":"tool_call","payload":{"tool":"read","status":"running"}}}
```

## Methods

| Method | Params | Result |
|--------|--------|--------|
| `agent.prompt` | `{text, auto_approve?, test_command?}` | `{task_id}` |
| `agent.steer` | `{task_id, content}` | `{ok: true}` |
| `agent.follow_up` | `{task_id, content}` | `{ok: true}` |
| `agent.abort` | `{task_id}` | `{ok: true}` |
| `agent.wait_idle` | `{task_id}` | `{status: "idle"}` |
| `agent.get_task` | `{task_id}` | task snapshot (same as HTTP GET `/api/tasks/{id}`) |
| `agent.diff` | `{task_id}` | `{diff}` |
| `agent.tree` | `{task_id}` | `{files: string[]}` |
| `agent.read_file` | `{task_id, path}` | `{path, content}` |
| `agent.approve` | `{task_id}` | `{ok: true}` |
| `agent.reject` | `{task_id}` | `{ok: true}` |
| `agent.rollback` | `{task_id}` | `{ok: true}` |
| `agent.accept` | `{task_id}` | `{ok: true}` |
| `session.load` | `{session_id?}` | `{session_id, head_id, messages, state}` |
| `session.branch` | `{session_id?, node_id}` | `{head_id}` |

## CLI

```bash
coderking rpc --workspace .
```

Pipe requests:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"agent.prompt","params":{"text":"hello"}}' | coderking rpc
```

## Backpressure

The server awaits stdout flush before emitting the next event notification when the previous write is still pending.
