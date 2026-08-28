# CoderKing SDK (embed mode)

In-process programmatic API — **no HTTP / RPC server**.

```python
from coderking_sdk import AgentSession

async with AgentSession(workspace=".", model="gpt-4o-mini") as session:
    async for event in session.run("fix the failing tests"):
        print(event["type"], event.get("payload"))
    await session.steer("also update README")
```

## Install

Monorepo (dev):

```bash
pip install -e ".[dev]"
```

Standalone (when published):

```bash
pip install coderking-sdk
```

## Threading / event loop

- One `AgentSession` ↔ **one asyncio event loop**
- Not safe to call the same session from multiple threads
- Jupyter: use the notebook's running loop (`await` in cells)
- FastAPI: create/use the session inside async route handlers on the app loop

## API

| Method | Role |
|--------|------|
| `run(prompt)` | Start task; async-iterate event records |
| `steer(text)` | Inject mid-run steering |
| `follow_up(text)` | Queue follow-up after current turn |
| `abort()` | Cancel the active task |
| `status()` | Public task snapshot dict |

Optional constructor args: `settings`, `llm` (tests/injection), `auto_approve`, `test_command`.

## Examples

See `examples/sdk_script_embed.py`, `examples/sdk_jupyter_embed.py`,
`examples/sdk_fastapi_embed.py`.
