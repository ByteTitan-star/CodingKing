"""Live connectivity probe. Never prints API keys."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from coderking.config import load_settings
from coderking.llm.openai_compat import OpenAICompatProvider
from coderking.llm.provider import LLMResponse

ROOT = Path(__file__).resolve().parents[1]


def _host_path(url: str) -> str:
    return url.split("://", 1)[-1]


async def probe(base_url: str) -> tuple[str, str]:
    settings = load_settings(workspace=ROOT, openai_base_url=base_url)
    if not settings.openai_api_key:
        return _host_path(base_url), "missing_key"
    provider = OpenAICompatProvider(settings)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a workspace file.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]
    messages = [
        {
            "role": "system",
            "content": "You are a coding agent. Call read_file with path=README.md.",
        },
        {"role": "user", "content": "Read README.md using the tool."},
    ]
    try:
        response: LLMResponse = await provider.complete(messages, tools)
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        text = text.replace(settings.openai_api_key, "[redacted]")
        return _host_path(base_url), f"error:{type(exc).__name__}:{text[:240]}"
    n = len(response.tool_calls)
    names = ",".join(c.name for c in response.tool_calls) or "-"
    content = "yes" if (response.content or "").strip() else "empty"
    return (
        _host_path(base_url),
        f"ok tools={n} names={names} content={content} tokens={response.prompt_tokens}+{response.completion_tokens}",
    )


async def main() -> None:
    load_dotenv(ROOT / ".env")
    current = os.environ.get("CODERKING_OPENAI_BASE_URL", "")
    candidates = []
    if current:
        candidates.append(current)
    for url in (
        "https://open.bigmodel.cn/api/paas/v4",
        "https://open.bigmodel.cn/api/coding/paas/v4",
    ):
        if url not in candidates:
            candidates.append(url)
    print(f"model={os.environ.get('CODERKING_MODEL', '')}")
    for url in candidates:
        label, result = await probe(url)
        print(f"{label} -> {result}")


if __name__ == "__main__":
    asyncio.run(main())
