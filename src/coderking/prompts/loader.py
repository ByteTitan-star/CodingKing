"""Load versioned system prompts from packaged markdown files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from coderking.config import Settings

PROMPTS_DIR = Path(__file__).resolve().parent
CORE_TOKEN_BUDGET = 1000


def estimate_text_tokens(text: str) -> int:
    """Heuristic tokenizer (about 4 chars per token) without external deps."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text.strip()


@lru_cache(maxsize=16)
def _read_prompt(relative_path: str) -> str:
    path = PROMPTS_DIR / relative_path
    return _strip_frontmatter(path.read_text(encoding="utf-8"))


def load_core_prompt() -> str:
    return _read_prompt("core.md")


def append_verification_hint(prompt: str, test_command: str | None) -> str:
    """Soft hint only — model still chooses when/how to verify via bash."""
    cmd = (test_command or "").strip()
    if not cmd:
        return prompt
    return (
        f"{prompt.rstrip()}\n\n"
        f"Preferred verification command for this task (run via bash when appropriate):\n"
        f"`{cmd}`\n"
    )


def resolve_system_prompt(
    settings: Settings,
    *,
    test_command: str | None = None,
) -> str:
    del settings  # reserved for future per-workspace prompt overlays
    return append_verification_hint(load_core_prompt(), test_command)
