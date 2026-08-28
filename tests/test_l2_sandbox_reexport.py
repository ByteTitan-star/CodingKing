"""L2 owns sandbox/shell; facade re-exports the same types."""

from __future__ import annotations

from coderking.diffing import snapshot_workspace
from coderking.runtime.cancel import CancellationToken, CancelledTask
from coderking.sandbox.base import ExecResult, Sandbox
from coderking.sandbox.cow import CowWorkspace
from coderking.sandbox.local import LocalProcessSandbox
from coderking.tools.shell import ShellTool
from coderking_agent_core.cancel import CancellationToken as L1Token
from coderking_agent_core.cancel import CancelledTask as L1Cancelled
from coderking_coding_agent.diffing import snapshot_workspace as l2_snapshot
from coderking_coding_agent.sandbox.base import ExecResult as L2Exec
from coderking_coding_agent.sandbox.base import Sandbox as L2Sandbox
from coderking_coding_agent.sandbox.cow import CowWorkspace as L2Cow
from coderking_coding_agent.sandbox.local import LocalProcessSandbox as L2Local
from coderking_coding_agent.tools.shell import ShellTool as L2Shell


def test_facade_reexports_l2_sandbox_and_shell() -> None:
    assert ExecResult is L2Exec
    assert Sandbox is L2Sandbox
    assert LocalProcessSandbox is L2Local
    assert CowWorkspace is L2Cow
    assert ShellTool is L2Shell
    assert snapshot_workspace is l2_snapshot
    assert CancellationToken is L1Token
    assert CancelledTask is L1Cancelled
