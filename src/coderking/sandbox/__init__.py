"""Sandbox package facade (#23)."""

from coderking.sandbox.base import ExecResult, Sandbox
from coderking.sandbox.manager import create_sandbox

__all__ = ["ExecResult", "Sandbox", "create_sandbox"]
