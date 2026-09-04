"""Helpers for live (real API) eval / E2E runs."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from coderking.config import Settings, load_settings

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_TASKS = REPO_ROOT / "eval" / "tasks"


def live_api_key() -> str:
    return (
        os.environ.get("CODERKING_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    ).strip()


def require_live_key() -> str:
    key = live_api_key()
    # CI unit jobs inject a placeholder "test-key" — treat as absent for live E2E.
    if not key or key in {"test-key", "x", "dummy"}:
        pytest.skip("live E2E requires CODERKING_OPENAI_API_KEY (real provider key)")
    return key


def live_settings(workspace: Path, **overrides: object) -> Settings:
    key = require_live_key()
    data = {
        "openai_api_key": key,
        "sandbox_mode": "local",
        "workspace": workspace,
        "max_iterations": 16,
    }
    data.update(overrides)
    base = load_settings(workspace=workspace)
    merged = {
        "openai_base_url": base.openai_base_url,
        "model": base.model,
        **data,
    }
    return Settings(**merged)


def copy_eval_repo(category: str, name: str, dest: Path) -> Path:
    src = EVAL_TASKS / category / name / "repo"
    if not src.is_dir():
        raise FileNotFoundError(src)
    shutil.copytree(src, dest)
    return dest
