"""Lazy-loaded skills from .coderking/skills and optional Cursor skills."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from coderking_coding_agent.context.budget import estimate_text_tokens

SKILL_TAG_RE = re.compile(r'<skill name="([^"]+)">', re.IGNORECASE)
DEFAULT_MAX_INJECT_TOKENS = 2000
FRONTMATTER_TOKEN_BUDGET = 100


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
    def __init__(self, workspace: Path, *, include_cursor: bool = True) -> None:
        self.workspace = workspace.resolve()
        self.include_cursor = include_cursor
        self._manifests: dict[str, SkillManifest] = {}
        self._body_cache: dict[str, tuple[str, str]] = {}
        self._scan()

    def manifests(self) -> list[SkillManifest]:
        return list(self._manifests.values())

    def get(self, name: str) -> SkillManifest | None:
        return self._manifests.get(name)

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
        if self.include_cursor:
            roots.append((Path.home() / ".cursor" / "skills", "cursor"))
        for root, source in roots:
            if not root.is_dir():
                continue
            for skill_dir in sorted(root.iterdir()):
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.is_file():
                    continue
                meta, _ = parse_skill_file(skill_md.read_text(encoding="utf-8"))
                name = str(meta.get("name") or skill_dir.name)
                if name in self._manifests and source == "cursor":
                    continue
                triggers_raw = meta.get("triggers") or []
                triggers = tuple(
                    str(item).strip().lower() for item in triggers_raw if str(item).strip()
                )
                description = str(meta.get("description") or name)
                max_tokens = int(meta.get("max_inject_tokens") or DEFAULT_MAX_INJECT_TOKENS)
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
            if any(trigger in haystack for trigger in manifest.triggers):
                hits.append(manifest)
        return hits


def inject_matching_skills(
    workspace: Path,
    messages: list[dict[str, Any]],
    prompt: str,
    recent_context: str = "",
    *,
    registry: SkillRegistry | None = None,
) -> tuple[list[dict[str, Any]], list[InjectedSkill]]:
    active = registry or SkillRegistry(workspace)
    already = activated_skill_names(messages)
    matched = SkillMatcher(active).match(prompt, recent_context)
    injected: list[InjectedSkill] = []
    updated = list(messages)
    insert_at = 1 if updated and updated[0].get("role") == "system" else 0
    offset = 0
    for manifest in matched:
        if manifest.name in already:
            continue
        skill = active.load_body(manifest.name)
        if skill is None:
            continue
        updated.insert(insert_at + offset, format_skill_message(skill))
        injected.append(skill)
        already.add(manifest.name)
        offset += 1
    return updated, injected
