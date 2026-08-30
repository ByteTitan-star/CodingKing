"""Unified safety policy engine for tool calls (Pi beforeToolCall style)."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

PolicyActionName = str


class PolicyAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    reason: str
    rule: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"action": self.action.value, "reason": self.reason, "rule": self.rule}


DEFAULT_POLICY: dict[str, Any] = {
    "tools": {
        "mcp_*": {"default_action": "ask"},
        "bash": {
            "deny_patterns": [
                r"rm\s+-rf\s+/",
                r"mkfs\b",
                r"dd\s+if=",
                r"shutdown\b",
                r"reboot\b",
                r":\(\)\{",
            ],
            "ask_patterns": [r"git\s+push", r"npm\s+publish"],
        },
        "shell": {
            "deny_patterns": [
                r"rm\s+-rf\s+/",
                r"mkfs\b",
                r"dd\s+if=",
                r"shutdown\b",
                r"reboot\b",
                r":\(\)\{",
            ],
            "ask_patterns": [r"git\s+push", r"npm\s+publish"],
        },
        "write": {
            "deny_paths": [".env", ".env.*", "**/secrets/**", "**/.env"],
        },
        "write_file": {
            "deny_paths": [".env", ".env.*", "**/secrets/**", "**/.env"],
        },
        "create_file": {
            "deny_paths": [".env", ".env.*", "**/secrets/**", "**/.env"],
        },
        "edit": {
            "deny_paths": [".env", ".env.*", "**/secrets/**", "**/.env"],
        },
        "edit_file": {
            "deny_paths": [".env", ".env.*", "**/secrets/**", "**/.env"],
        },
        "delete_file": {"default_action": "ask"},
        "git_commit": {"default_action": "ask"},
    }
}


def policy_yaml_path(workspace: Path) -> Path:
    return workspace.resolve() / ".coderking" / "policy.yaml"


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")


def _path_matches(pattern: str, rel_path: str) -> bool:
    normalized = _normalize_path(rel_path)
    pattern_norm = _normalize_path(pattern)
    if fnmatch.fnmatch(normalized, pattern_norm):
        return True
    basename = Path(normalized).name
    return fnmatch.fnmatch(basename, pattern_norm)


class PolicyEngine:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.tools: dict[str, Any] = dict(config.get("tools") or {})

    @classmethod
    def load(cls, workspace: Path) -> PolicyEngine:
        path = policy_yaml_path(workspace)
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                data = {}
            merged = _merge_policy(DEFAULT_POLICY, data)
            return cls(merged)
        return cls(dict(DEFAULT_POLICY))

    def evaluate(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        legacy_requires_approval: bool = False,
    ) -> PolicyDecision:
        rules = self.tools.get(tool_name)
        if rules is None:
            for pattern, candidate in self.tools.items():
                if fnmatch.fnmatch(tool_name, str(pattern)):
                    rules = candidate
                    break
        if rules is None and tool_name.startswith("mcp_"):
            rules = {"default_action": "ask"}
        rules = rules or {}
        command = str(arguments.get("command") or "")
        if command:
            denied = _match_patterns(command, rules.get("deny_patterns") or [], regex=True)
            if denied:
                return PolicyDecision(PolicyAction.DENY, f"deny pattern matched: {denied}", denied)
            asked = _match_patterns(command, rules.get("ask_patterns") or [], regex=True)
            if asked:
                return PolicyDecision(PolicyAction.ASK, f"ask pattern matched: {asked}", asked)

        rel_path = str(arguments.get("path") or "")
        if rel_path:
            for pattern in rules.get("deny_paths") or []:
                if _path_matches(str(pattern), rel_path):
                    return PolicyDecision(
                        PolicyAction.DENY,
                        f"deny path matched: {pattern}",
                        str(pattern),
                    )

        default_action = rules.get("default_action")
        if default_action == "deny":
            return PolicyDecision(
                PolicyAction.DENY,
                "tool denied by policy default",
                "default_action",
            )
        if default_action == "ask" or legacy_requires_approval:
            reason = (
                "policy requires approval" if default_action == "ask" else "legacy tool approval"
            )
            return PolicyDecision(PolicyAction.ASK, reason, "default_action")

        return PolicyDecision(PolicyAction.ALLOW, "allowed", None)

    def evaluate_batch(
        self,
        calls: list[tuple[str, dict[str, Any]]],
        *,
        legacy_flags: dict[str, bool] | None = None,
    ) -> list[PolicyDecision]:
        flags = legacy_flags or {}
        return [
            self.evaluate(name, args, legacy_requires_approval=flags.get(name, False))
            for name, args in calls
        ]


def _match_patterns(text: str, patterns: list[Any], *, regex: bool) -> str | None:
    for raw in patterns:
        pattern = str(raw)
        if regex:
            if re.search(pattern, text, re.I):
                return pattern
        elif pattern.lower() in text.lower():
            return pattern
    return None


_ACTION_STRENGTH = {"allow": 0, "ask": 1, "deny": 2}


def _stricter_default_action(base: object, override: object) -> str | None:
    """Workspace policy may only tighten default_action, never weaken it."""
    base_s = str(base).lower() if base is not None else None
    override_s = str(override).lower() if override is not None else None
    if base_s not in _ACTION_STRENGTH and override_s not in _ACTION_STRENGTH:
        return None
    if base_s not in _ACTION_STRENGTH:
        return override_s
    if override_s not in _ACTION_STRENGTH:
        return base_s
    return base_s if _ACTION_STRENGTH[base_s] >= _ACTION_STRENGTH[override_s] else override_s


def _merge_policy(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = {"tools": dict(base.get("tools") or {})}
    for name, rules in (override.get("tools") or {}).items():
        if not isinstance(rules, dict):
            continue
        current = dict(merged["tools"].get(name) or {})
        for key, value in rules.items():
            if key == "default_action":
                current[key] = _stricter_default_action(current.get(key), value)
                continue
            if isinstance(value, list) and isinstance(current.get(key), list):
                current[key] = [*current[key], *value]
            else:
                current[key] = value
        # Apply wildcard floors (e.g. mcp_*) when override adds a concrete tool.
        if "default_action" not in current:
            for pattern, candidate in (base.get("tools") or {}).items():
                if not isinstance(candidate, dict):
                    continue
                if name == pattern or ("*" in str(pattern) and fnmatch.fnmatch(name, str(pattern))):
                    floor = candidate.get("default_action")
                    if floor is not None:
                        current["default_action"] = _stricter_default_action(
                            floor, current.get("default_action")
                        )
                    break
        merged["tools"][name] = current
    return merged
