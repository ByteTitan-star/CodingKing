"""Non-live guard: live helpers skip without a real key."""

from __future__ import annotations

import pytest
from tests.e2e.conftest import require_live_key


def test_require_live_key_skips_for_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODERKING_OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(pytest.skip.Exception):
        require_live_key()
