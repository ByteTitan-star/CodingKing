"""Load versioned system prompts from packaged markdown files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from coderking.config import Settings
from coderking.runtime.state import Role

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


def load_swe_role_prompt(role: Role) -> str:
    return _read_prompt(f"swe/{role.value}.md")


def resolve_system_prompt(settings: Settings, role: Role) -> str:
    if settings.extension == "atomic":
        return load_core_prompt()
    return load_swe_role_prompt(role)
