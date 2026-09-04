"""Facade re-exports L2 coding-agent runtime types."""

from __future__ import annotations

from coderking.runtime.events import AgentEvent
from coderking.runtime.queues import RunMessageQueues
from coderking.runtime.roles import Role
from coderking.runtime.state import AgentState, TaskStatus
from coderking_coding_agent.runtime.atomic_l1 import AtomicL1Runtime
from coderking_coding_agent.runtime.events import AgentEvent as L2Event
from coderking_coding_agent.runtime.queues import RunMessageQueues as L2Queues
from coderking_coding_agent.runtime.state import AgentState as L2State
from coderking_coding_agent.runtime.state import Role as L2Role
from coderking_coding_agent.runtime.state import TaskStatus as L2Status


def test_facade_reexports_l2_runtime_types() -> None:
    assert AgentEvent is L2Event
    assert RunMessageQueues is L2Queues
    assert AgentState is L2State
    assert Role is L2Role
    assert TaskStatus is L2Status
    assert AtomicL1Runtime is not None
