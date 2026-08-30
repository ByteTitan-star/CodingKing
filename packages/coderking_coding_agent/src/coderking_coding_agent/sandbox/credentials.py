"""Credential isolation helpers for sandbox processes and mounts."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from fnmatch import fnmatch
from pathlib import Path

# Host-only secrets — never injected into sandbox child processes / containers.
SECRET_ENV_PREFIXES = (
    "CODERKING_",
    "OPENAI_",
    "ANTHROPIC_",
    "AZURE_OPENAI_",
    "AWS_",
    "GOOGLE_",
    "GEMINI_",
    "DEEPSEEK_",
)

SECRET_ENV_NAMES = frozenset(
    {
        "API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
    }
)

# Allowlisted env vars passed into sandbox (plus PATH / locale essentials).
SANDBOX_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "PATHEXT",
        "HOME",
        "USER",
        "USERNAME",
        "USERPROFILE",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TMP",
        "TEMP",
        "TMPDIR",
        "SystemRoot",
        "SYSTEMROOT",
        "ComSpec",
        "COMSPEC",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "TZ",
    }
)

# Paths excluded from CoW clones / mounts (dockerignore-style).
SECRET_PATH_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*credentials*",
    "*secret*",
    ".git/config",
    ".coderking",
)

_SECRET_VALUE_RE = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-)")


def is_secret_env_name(name: str) -> bool:
    upper = name.upper()
    if upper in SECRET_ENV_NAMES:
        return True
    return any(upper.startswith(prefix) for prefix in SECRET_ENV_PREFIXES)


def scrub_env(
    env: Mapping[str, str] | None = None,
    *,
    allowlist_only: bool = False,
) -> dict[str, str]:
    """Return a sandbox-safe environment.

    By default strips secret names/prefixes but keeps developer tooling vars
    (e.g. APPDATA for user site-packages). Pass ``allowlist_only=True`` for
    minimal Docker-style env construction from an explicit source mapping.
    """
    source = dict(env if env is not None else os.environ)
    cleaned: dict[str, str] = {}
    for key, value in source.items():
        if is_secret_env_name(key):
            continue
        if allowlist_only and key not in SANDBOX_ENV_ALLOWLIST and not key.startswith("LC_"):
            continue
        cleaned[key] = value
    if allowlist_only and "PATH" not in cleaned and "PATH" in source:
        cleaned["PATH"] = source["PATH"]
    cleaned.setdefault("PYTHONIOENCODING", "utf-8")
    return cleaned


def is_secret_path(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    basename = normalized.rsplit("/", 1)[-1]
    for pattern in SECRET_PATH_PATTERNS:
        if fnmatch(normalized, pattern) or fnmatch(basename, pattern):
            return True
        parts = normalized.split("/")
        if any(fnmatch(part, pattern) for part in parts):
            return True
    return False


def secret_ignore_names(directory: str, names: list[str]) -> set[str]:
    """shutil.copytree ignore callback for secret paths + SKIP_DIRS."""
    from coderking_coding_agent.workspace import SKIP_DIRS

    ignored: set[str] = set()
    parent = Path(directory).name
    for name in names:
        if name in SKIP_DIRS:
            ignored.add(name)
            continue
        if is_secret_path(name) or is_secret_path(f"{parent}/{name}"):
            ignored.add(name)
    return ignored


def contains_secret_marker(text: str) -> bool:
    return bool(_SECRET_VALUE_RE.search(text))


def scrub_secret_text(text: str) -> str:
    return _SECRET_VALUE_RE.sub("<redacted>", text)


_SENSITIVE_ARG_KEYS = frozenset(
    {
        "content",
        "token",
        "password",
        "secret",
        "api_key",
        "apikey",
        "authorization",
        "auth",
    }
)
_SENSITIVE_KEY_FRAGMENTS = ("secret", "token", "password", "api_key", "apikey")


def redact_tool_arguments(arguments: dict[str, object], *, max_len: int = 200) -> dict[str, object]:
    """Return a copy of tool arguments safe for audit / report persistence."""
    redacted: dict[str, object] = {}
    for key, value in arguments.items():
        key_l = str(key).lower()
        sensitive_key = key_l in _SENSITIVE_ARG_KEYS or any(
            frag in key_l for frag in _SENSITIVE_KEY_FRAGMENTS
        )
        if sensitive_key:
            text = str(value)
            redacted[key] = f"<redacted len={len(text)}>"
            continue
        if isinstance(value, str):
            text = (
                _SECRET_VALUE_RE.sub("<redacted>", value)
                if contains_secret_marker(value)
                else value
            )
            if len(text) > max_len:
                redacted[key] = text[:max_len] + f"…<truncated n={len(text) - max_len}>"
            else:
                redacted[key] = text
        elif isinstance(value, dict):
            redacted[key] = redact_tool_arguments(value, max_len=max_len)  # type: ignore[arg-type]
        else:
            redacted[key] = value
    return redacted
