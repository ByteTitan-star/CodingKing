"""L1: pure agent loop (no coding-domain logic)."""

from __future__ import annotations

from coderking_agent_core.agent import Agent
from coderking_agent_core.cancel import CancelledRun, RunCancel
from coderking_agent_core.fsm import InvalidPhaseTransition, LoopEvent, PhaseFSM, PhaseHooks
from coderking_agent_core.loop import (
    AgentLoopConfig,
    ToolCallRequest,
    TurnResult,
    new_tool_call,
    run_agent_loop,
)
from coderking_agent_core.types import (
    AgentContext,
    AgentMessage,
    AgentTool,
    LoopPhase,
)

LAYER = 1
LAYER_NAME = "agent_core"
__version__ = "0.1.0"

__all__ = [
    "LAYER",
    "LAYER_NAME",
    "Agent",
    "AgentContext",
    "AgentLoopConfig",
    "AgentMessage",
    "AgentTool",
    "CancelledRun",
    "InvalidPhaseTransition",
    "LoopEvent",
    "LoopPhase",
    "PhaseFSM",
    "PhaseHooks",
    "RunCancel",
    "ToolCallRequest",
    "TurnResult",
    "new_tool_call",
    "run_agent_loop",
    "__version__",
]
