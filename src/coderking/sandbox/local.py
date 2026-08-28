"""Facade re-export (#23)."""

from __future__ import annotations

from coderking_coding_agent.sandbox.local import LocalProcessSandbox, _communicate, _kill

__all__ = ["LocalProcessSandbox", "_communicate", "_kill"]
