"""Dynamic context compression for long agent sessions."""

from coderking_coding_agent.context.budget import TokenBudget, estimate_messages_tokens
from coderking_coding_agent.context.compress import CompressionSummary, phase_a_compress
from coderking_coding_agent.context.project_docs import (
    ProjectInstructions,
    ProjectInstructionsLoader,
    inject_project_instructions,
)
from coderking_coding_agent.context.skills import SkillRegistry, inject_matching_skills
from coderking_coding_agent.context.transform import ContextCompressor, make_transform_context

__all__ = [
    "CompressionSummary",
    "ContextCompressor",
    "ProjectInstructions",
    "ProjectInstructionsLoader",
    "SkillRegistry",
    "TokenBudget",
    "estimate_messages_tokens",
    "inject_matching_skills",
    "inject_project_instructions",
    "make_transform_context",
    "phase_a_compress",
]
