"""SWE harness extension — legacy 5-role toolset and workflow."""

from __future__ import annotations

from coderking_coding_agent.extensions import Extension, ExtensionRegistry

SWE_EXTENSION = Extension(
    name="swe",
    description=(
        "Software-engineering harness: 5 roles, git/test/search tools, and meta workflow tools."
    ),
    register=lambda _ctx: None,
    metadata={
        "tool_profile": "swe",
        "roles": ["planner", "coding", "execution", "reviewer", "repair"],
    },
)


def register_swe(registry: ExtensionRegistry) -> None:
    registry.add(SWE_EXTENSION)


def default_registry() -> ExtensionRegistry:
    registry = ExtensionRegistry()
    register_swe(registry)
    return registry
