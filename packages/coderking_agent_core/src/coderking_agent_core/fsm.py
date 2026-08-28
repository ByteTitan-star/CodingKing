"""Deterministic five-phase agent loop FSM (Pi turn mapping)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum

from coderking_agent_core.types import LoopPhase

PhaseHook = Callable[[LoopPhase, LoopPhase], Awaitable[None]]


class LoopEvent(StrEnum):
    CONTEXT_READY = "context_ready"
    ASSISTANT_WITH_TOOLS = "assistant_with_tools"
    ASSISTANT_NO_TOOLS = "assistant_no_tools"
    TOOLS_DONE = "tools_done"
    RESULTS_APPENDED = "results_appended"
    CONTINUE = "continue"
    TERMINATE = "terminate"


class InvalidPhaseTransition(Exception):
    def __init__(self, phase: LoopPhase, event: LoopEvent) -> None:
        self.phase = phase
        self.event = event
        super().__init__(f"invalid transition: {phase.value} + {event.value}")


_TRANSITIONS: dict[tuple[LoopPhase, LoopEvent], LoopPhase] = {
    (LoopPhase.PERCEIVE, LoopEvent.CONTEXT_READY): LoopPhase.DECIDE,
    (LoopPhase.DECIDE, LoopEvent.ASSISTANT_WITH_TOOLS): LoopPhase.ACT,
    (LoopPhase.DECIDE, LoopEvent.ASSISTANT_NO_TOOLS): LoopPhase.RE_PERCEIVE,
    (LoopPhase.ACT, LoopEvent.TOOLS_DONE): LoopPhase.OBSERVE,
    (LoopPhase.OBSERVE, LoopEvent.RESULTS_APPENDED): LoopPhase.RE_PERCEIVE,
    (LoopPhase.RE_PERCEIVE, LoopEvent.CONTINUE): LoopPhase.PERCEIVE,
}

for _phase in LoopPhase:
    if _phase != LoopPhase.TERMINATED:
        _TRANSITIONS[(_phase, LoopEvent.TERMINATE)] = LoopPhase.TERMINATED


@dataclass
class PhaseHooks:
    on_enter: dict[LoopPhase, PhaseHook] = field(default_factory=dict)


@dataclass
class PhaseFSM:
    """Explicit loop phase state machine with validated transitions."""

    phase: LoopPhase = LoopPhase.PERCEIVE
    hooks: PhaseHooks = field(default_factory=PhaseHooks)

    def transition(self, event: LoopEvent) -> LoopPhase:
        key = (self.phase, event)
        next_phase = _TRANSITIONS.get(key)
        if next_phase is None:
            raise InvalidPhaseTransition(self.phase, event)
        previous = self.phase
        self.phase = next_phase
        return previous

    async def advance(
        self,
        event: LoopEvent,
        *,
        on_phase_change: Callable[[LoopPhase, LoopPhase], Awaitable[None]] | None = None,
    ) -> LoopPhase:
        previous = self.transition(event)
        if self.phase != previous and on_phase_change is not None:
            await on_phase_change(previous, self.phase)
        hook = self.hooks.on_enter.get(self.phase)
        if hook is not None:
            await hook(previous, self.phase)
        return self.phase
