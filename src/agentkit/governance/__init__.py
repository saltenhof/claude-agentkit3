"""Governance module -- guards, integrity gates, and policy enforcement.

Re-exports the public API so consumers can write::

    from agentkit.governance import GuardVerdict, BranchGuard, GuardRunner
"""

from __future__ import annotations

from agentkit.governance.guards.artifact_guard import ArtifactGuard
from agentkit.governance.guards.branch_guard import BranchGuard
from agentkit.governance.guards.scope_guard import ScopeGuard
from agentkit.governance.integrity_gate import (
    IntegrityCheckResult,
    IntegrityGate,
    IntegrityGateResult,
)
from agentkit.governance.protocols import (
    GovernanceGuard,
    GuardVerdict,
    ViolationType,
)
from agentkit.governance.runner import GuardRunner

__all__ = [
    "ArtifactGuard",
    "BranchGuard",
    "GovernanceGuard",
    "GuardRunner",
    "GuardVerdict",
    "IntegrityCheckResult",
    "IntegrityGate",
    "IntegrityGateResult",
    "ScopeGuard",
    "ViolationType",
]
