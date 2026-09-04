from __future__ import annotations

import coderking_agent_core
import coderking_coding_agent
import coderking_llm
import coderking_transport
from coderking_agent_core.fsm import InvalidPhaseTransition, LoopEvent, PhaseFSM
from coderking_agent_core.types import AgentContext, LoopPhase
from coderking_coding_agent.extensions import ExtensionRegistry
from coderking_llm.protocols import StopReason, UsageStats
from coderking_transport.channels import TransportKind


def test_layer_packages_importable() -> None:
    assert coderking_llm.LAYER == 0
    assert coderking_agent_core.LAYER == 1
    assert coderking_coding_agent.LAYER == 2
    assert coderking_transport.LAYER == 3


def test_layer_contracts_are_usable() -> None:
    assert StopReason.TOOL_USE.value == "tool_use"
    assert UsageStats(1, 2).total_tokens == 3
    assert LoopPhase.DECIDE == "decide"
    assert PhaseFSM().phase == LoopPhase.PERCEIVE
    assert issubclass(InvalidPhaseTransition, Exception)
    assert LoopEvent.CONTINUE == "continue"
    ctx = AgentContext(system_prompt="x")
    assert ctx.messages == []
    assert ExtensionRegistry().names() == []
    assert TransportKind.RPC_STDIO == "rpc_stdio"
    assert TransportKind.TUI == "tui"
