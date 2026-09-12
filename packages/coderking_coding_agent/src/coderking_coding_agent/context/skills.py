"""Lazy-loaded skills from .coderking/skills and optional Cursor skills."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from coderking_coding_agent.context.budget import estimate_text_tokens

SKILL_TAG_RE = re.compile(r'<skill name="([^"]+)">', re.IGNORECASE)
DEFAULT_MAX_INJECT_TOKENS = 2000
FRONTMATTER_TOKEN_BUDGET = 100
MAX_SKILL_INJECT_TOKENS = 20_000


@dataclass(frozen=True)
class SkillManifest:
    name: str
    description: str
    triggers: tuple[str, ...]
    max_inject_tokens: int
    path: Path
    source: str


@dataclass(frozen=True)
class InjectedSkill:
    manifest: SkillManifest
    content: str
    truncated: bool


def parse_skill_file(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            meta = yaml.safe_load(parts[1]) or {}
            if not isinstance(meta, dict):
                meta = {}
            return meta, parts[2].strip()
    return {}, text.strip()


def _truncate_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    max_chars = max(1, max_tokens) * 4
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def format_skill_message(skill: InjectedSkill) -> dict[str, Any]:
    body = skill.content.strip()
    text = f'<skill name="{skill.manifest.name}">\n{body}\n</skill>'
    return {
        "role": "user",
        "content": text,
        "meta": {
            "skill": skill.manifest.name,
            "truncated": skill.truncated,
            "source": skill.manifest.source,
        },
    }


def activated_skill_names(messages: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for message in messages:
        meta = message.get("meta") or {}
        if isinstance(meta, dict) and meta.get("skill"):
            names.add(str(meta["skill"]))
        content = str(message.get("content") or "")
        names.update(SKILL_TAG_RE.findall(content))
    return names


class SkillRegistry:
    def __init__(
        self,
        workspace: Path,
        *,
        include_cursor: bool = True,
        include_global: bool = True,
        global_root: Path | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.include_cursor = include_cursor
        self.include_global = include_global
        self.global_root = (global_root or Path.home() / ".coderking" / "skills").resolve()
        self._manifests: dict[str, SkillManifest] = {}
        self._body_cache: dict[str, tuple[str, str]] = {}
        self._diagnostics: list[str] = []
        self._scan()

    def manifests(self) -> list[SkillManifest]:
        return list(self._manifests.values())

    def get(self, name: str) -> SkillManifest | None:
        direct = self._manifests.get(name)
        if direct is not None:
            return direct
        folded = name.casefold()
        return next(
            (manifest for key, manifest in self._manifests.items() if key.casefold() == folded),
            None,
        )

    def diagnostics(self) -> tuple[str, ...]:
        return tuple(self._diagnostics)

    def frontmatter_token_estimate(self) -> int:
        total = 0
        for manifest in self._manifests.values():
            chunk = f"{manifest.name} {manifest.description} {' '.join(manifest.triggers)}"
            total += min(FRONTMATTER_TOKEN_BUDGET, estimate_text_tokens(chunk))
        return total

    def inspect(self) -> dict[str, Any]:
        return {
            "count": len(self._manifests),
            "frontmatter_tokens": self.frontmatter_token_estimate(),
            "diagnostics": list(self._diagnostics),
            "skills": [
                {
                    "name": item.name,
                    "description": item.description,
                    "triggers": list(item.triggers),
                    "source": item.source,
                }
                for item in self.manifests()
            ],
        }

    def load_body(self, name: str) -> InjectedSkill | None:
        manifest = self._manifests.get(name)
        if manifest is None:
            return None
        cache_key = self._body_cache.get(name)
        stat = manifest.path.stat()
        current_key = f"{stat.st_mtime_ns}:{stat.st_size}"
        if cache_key and cache_key[0] == current_key:
            body = cache_key[1]
        else:
            _, body = parse_skill_file(manifest.path.read_text(encoding="utf-8"))
            self._body_cache[name] = (current_key, body)
        clipped, truncated = _truncate_to_tokens(body, manifest.max_inject_tokens)
        return InjectedSkill(manifest=manifest, content=clipped, truncated=truncated)

    def _scan(self) -> None:
        roots: list[tuple[Path, str]] = [(self.workspace / ".coderking" / "skills", "workspace")]
        if self.include_global:
            roots.append((self.global_root, "global"))
        if self.include_cursor:
            roots.append((Path.home() / ".cursor" / "skills", "cursor"))
        for root, source in roots:
            if not root.is_dir():
                continue
            for skill_md in sorted(root.rglob("SKILL.md")):
                skill_dir = skill_md.parent
                try:
                    meta, _ = parse_skill_file(skill_md.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, yaml.YAMLError) as exc:
                    self._diagnostics.append(f"{skill_md}: {exc}")
                    continue
                name = str(meta.get("name") or skill_dir.name)
                if not name.strip():
                    self._diagnostics.append(f"{skill_md}: skill name is empty")
                    continue
                if self.get(name) is not None:
                    self._diagnostics.append(
                        f"{skill_md}: duplicate skill {name!r}; higher-priority definition kept"
                    )
                    continue
                triggers_raw = meta.get("triggers") or []
                if isinstance(triggers_raw, str):
                    triggers_raw = [triggers_raw]
                triggers = tuple(
                    str(item).strip().lower() for item in triggers_raw if str(item).strip()
                )
                description = str(meta.get("description") or name)
                try:
                    max_tokens = int(meta.get("max_inject_tokens") or DEFAULT_MAX_INJECT_TOKENS)
                except (TypeError, ValueError):
                    self._diagnostics.append(f"{skill_md}: max_inject_tokens must be an integer")
                    continue
                if not 1 <= max_tokens <= MAX_SKILL_INJECT_TOKENS:
                    self._diagnostics.append(
                        f"{skill_md}: max_inject_tokens must be between 1 and "
                        f"{MAX_SKILL_INJECT_TOKENS}"
                    )
                    continue
                self._manifests[name] = SkillManifest(
                    name=name,
                    description=description,
                    triggers=triggers,
                    max_inject_tokens=max_tokens,
                    path=skill_md,
                    source=source,
                )


class SkillMatcher:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def match(self, prompt: str, recent_context: str = "") -> list[SkillManifest]:
        haystack = f"{prompt}\n{recent_context}".lower()
        hits: list[SkillManifest] = []
        for manifest in self.registry.manifests():
            explicit_names = {
                f"${manifest.name.lower()}",
                f"/skill:{manifest.name.lower()}",
            }
            matched_explicitly = any(name in haystack for name in explicit_names)
            if matched_explicitly or any(trigger in haystack for trigger in manifest.triggers):
                hits.append(manifest)
        return hits


def inject_matching_skills(
    workspace: Path,
    messages: list[dict[str, Any]],
    prompt: str,
    recent_context: str = "",
    *,
    registry: SkillRegistry | None = None,
    insert_at: int | None = None,
) -> tuple[list[dict[str, Any]], list[InjectedSkill]]:
    active = registry or SkillRegistry(workspace)
    already = activated_skill_names(messages)
    matched = SkillMatcher(active).match(prompt, recent_context)
    injected: list[InjectedSkill] = []
    updated = list(messages)
    position = (
        insert_at
        if insert_at is not None
        else (1 if updated and updated[0].get("role") == "system" else 0)
    )
    offset = 0
    for manifest in matched:
        if manifest.name in already:
            continue
        skill = active.load_body(manifest.name)
        if skill is None:
            continue
        updated.insert(position + offset, format_skill_message(skill))
        injected.append(skill)
        already.add(manifest.name)
        offset += 1
    return updated, injected


def inject_named_skills(
    messages: list[dict[str, Any]],
    names: Sequence[str],
    *,
    registry: SkillRegistry,
    insert_at: int | None = None,
) -> tuple[list[dict[str, Any]], list[InjectedSkill]]:
    """Inject explicitly selected skills or fail with a useful error."""
    already = activated_skill_names(messages)
    updated = list(messages)
    position = insert_at if insert_at is not None else len(updated)
    injected: list[InjectedSkill] = []
    for requested in names:
        manifest = registry.get(requested.strip())
        if manifest is None:
            available = ", ".join(item.name for item in registry.manifests()) or "none"
            raise ValueError(f"unknown skill {requested!r}; available skills: {available}")
        if manifest.name in already:
            continue
        skill = registry.load_body(manifest.name)
        if skill is None:
            raise ValueError(f"skill {manifest.name!r} could not be loaded")
        updated.insert(position + len(injected), format_skill_message(skill))
        injected.append(skill)
        already.add(manifest.name)
    return updated, injected
