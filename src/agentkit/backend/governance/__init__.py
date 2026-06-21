"""Governance module -- guards, integrity gates, and policy enforcement.

Re-exports the public API so consumers can write::

    from agentkit.backend.governance import GuardVerdict, BranchGuard, GuardRunner
"""

from __future__ import annotations

from agentkit.backend.governance.guards.artifact_guard import ArtifactGuard
from agentkit.backend.governance.guards.branch_guard import BranchGuard
from agentkit.backend.governance.guards.scope_guard import ScopeGuard
from agentkit.backend.governance.integrity_gate import (
    DimensionResult,
    IntegrityDimension,
    IntegrityGate,
    IntegrityGateResult,
    IntegrityGateStatus,
)
from agentkit.backend.governance.protocols import (
    GovernanceGuard,
    GuardVerdict,
    ViolationType,
)
from agentkit.backend.governance.runner import Governance, GuardRunner, HookDecision

__all__ = [
    "ArtifactGuard",
    "BranchGuard",
    "GovernanceGuard",
    "Governance",
    "GuardRunner",
    "GuardVerdict",
    "DimensionResult",
    "HookDecision",
    "IntegrityDimension",
    "IntegrityGate",
    "IntegrityGateResult",
    "IntegrityGateStatus",
    "ScopeGuard",
    "ViolationType",
]
