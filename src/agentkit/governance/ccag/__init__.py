"""CCAG — Claude Code Agent Governance permission runtime (FK-42).

Sub-component of the ``governance-and-guards`` BC.  Implements the
learnable, session-persistent permission layer for tool calls.

Public surface:
    :class:`~agentkit.governance.ccag.runtime.CcagPermissionRuntime` — evaluate(HookEvent) -> CcagDecision
    :class:`~agentkit.governance.ccag.runtime.CcagDecision` — decision result
    :class:`~agentkit.governance.ccag.runtime.CcagDecisionKind` — decision enum
    :class:`~agentkit.governance.ccag.leases.PermissionLeaseStore` — consume-once leases
    :class:`~agentkit.governance.ccag.requests.PermissionRequestStore` — pending requests

See FK-42 for the full specification.
"""

from __future__ import annotations

from agentkit.governance.ccag.leases import (
    LeaseExhaustedError,
    LeaseExpiredError,
    LeaseNotFoundError,
    PermissionLease,
    PermissionLeaseStore,
)
from agentkit.governance.ccag.requests import (
    PermissionRequest,
    PermissionRequestStore,
)
from agentkit.governance.ccag.runtime import (
    CcagDecision,
    CcagDecisionKind,
    CcagPermissionRuntime,
)

__all__ = [
    "CcagDecision",
    "CcagDecisionKind",
    "CcagPermissionRuntime",
    "LeaseExhaustedError",
    "LeaseExpiredError",
    "LeaseNotFoundError",
    "PermissionLease",
    "PermissionLeaseStore",
    "PermissionRequest",
    "PermissionRequestStore",
]
