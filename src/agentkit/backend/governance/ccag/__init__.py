"""CCAG — Claude Code Agent Governance permission runtime (FK-42).

Sub-component of the ``governance-and-guards`` BC.  Implements the
learnable, session-persistent permission layer for tool calls.

Public surface:
    :class:`~agentkit.backend.governance.ccag.runtime.CcagPermissionRuntime` — evaluate(HookEvent) -> CcagDecision
    :class:`~agentkit.backend.governance.ccag.runtime.CcagDecision` — decision result
    :class:`~agentkit.backend.governance.ccag.runtime.CcagDecisionKind` — decision enum
    :class:`~agentkit.backend.governance.ccag.permission_service.PermissionService` — central lifecycle owner

See FK-42 for the full specification.
"""

from __future__ import annotations

from agentkit.backend.governance.ccag.leases import (
    LeaseExhaustedError,
    LeaseExpiredError,
    LeaseNotFoundError,
    PermissionLease,
)
from agentkit.backend.governance.ccag.permission_service import PermissionService
from agentkit.backend.governance.ccag.requests import (
    PermissionRequest,
)
from agentkit.backend.governance.ccag.runtime import (
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
    "PermissionService",
    "PermissionRequest",
]
