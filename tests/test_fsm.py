from __future__ import annotations

import pytest

from coderking_agent_core.fsm import InvalidPhaseTransition, LoopEvent, PhaseFSM
from coderking_agent_core.types import LoopPhase


def test_perceive_to_decide_to_act_to_observe_to_re_perceive() -> None:
    fsm = PhaseFSM()
    assert fsm.phase == LoopPhase.PERCEIVE
    fsm.transition(LoopEvent.CONTEXT_READY)
    assert fsm.phase == LoopPhase.DECIDE
    fsm.transition(LoopEvent.ASSISTANT_WITH_TOOLS)
    assert fsm.phase == LoopPhase.ACT
    fsm.transition(LoopEvent.TOOLS_DONE)
    assert fsm.phase == LoopPhase.OBSERVE
    fsm.transition(LoopEvent.RESULTS_APPENDED)
    assert fsm.phase == LoopPhase.RE_PERCEIVE
    fsm.transition(LoopEvent.CONTINUE)
    assert fsm.phase == LoopPhase.PERCEIVE


def test_decide_without_tools_skips_act_observe() -> None:
    fsm = PhaseFSM()
    fsm.transition(LoopEvent.CONTEXT_READY)
    fsm.transition(LoopEvent.ASSISTANT_NO_TOOLS)
    assert fsm.phase == LoopPhase.RE_PERCEIVE


def test_illegal_transition_raises() -> None:
    fsm = PhaseFSM()
    with pytest.raises(InvalidPhaseTransition):
        fsm.transition(LoopEvent.TOOLS_DONE)


def test_terminate_from_any_phase() -> None:
    for start in (
        LoopPhase.PERCEIVE,
        LoopPhase.DECIDE,
        LoopPhase.ACT,
        LoopPhase.OBSERVE,
        LoopPhase.RE_PERCEIVE,
    ):
        fsm = PhaseFSM(phase=start)
        fsm.transition(LoopEvent.TERMINATE)
        assert fsm.phase == LoopPhase.TERMINATED


@pytest.mark.asyncio
async def test_advance_invokes_phase_change_callback() -> None:
    fsm = PhaseFSM()
    changes: list[tuple[str, str]] = []

    async def on_change(previous: LoopPhase, current: LoopPhase) -> None:
        changes.append((previous.value, current.value))

    await fsm.advance(LoopEvent.CONTEXT_READY, on_phase_change=on_change)
    assert changes == [("perceive", "decide")]
