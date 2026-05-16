"""Governance module -- guards, integrity gates, and policy enforcement.

Re-exports the public API so consumers can write::

    from agentkit.governance import GuardVerdict, BranchGuard, GuardRunner
"""

from __future__ import annotations

from agentkit.governance.guards.artifact_guard import ArtifactGuard
from agentkit.governance.guards.branch_guard import BranchGuard
from agentkit.governance.guards.scope_guard import ScopeGuard
from agentkit.governance.protocols import (
    GovernanceGuard,
    GuardVerdict,
    ViolationType,
)
from agentkit.governance.runner import Governance, GuardRunner, HookDecision


def __getattr__(name: str) -> object:
    """Lazy-load integrity_gate exports to break the verify_system circular import.

    ``governance.integrity_gate`` imports ``verify_system.verify_decision_passed``.
    ``verify_system.artifacts`` imports ``governance.guard_system.protected_paths``.
    Loading ``governance.__init__`` eagerly while ``verify_system`` is being
    initialized causes a circular ImportError. Lazy-loading integrity_gate
    breaks the cycle (integrity_gate is only needed at call-time, not at
    import-time of the governance package).
    """
    if name in ("IntegrityCheckResult", "IntegrityGate", "IntegrityGateResult"):
        # Inject into module namespace so repeated access is direct
        import agentkit.governance as _self  # noqa: PLC0415
        from agentkit.governance.integrity_gate import (  # noqa: PLC0415
            IntegrityCheckResult,
            IntegrityGate,
            IntegrityGateResult,
        )
        _self.IntegrityCheckResult = IntegrityCheckResult
        _self.IntegrityGate = IntegrityGate
        _self.IntegrityGateResult = IntegrityGateResult
        return locals()[name]
    raise AttributeError(f"module 'agentkit.governance' has no attribute {name!r}")

__all__ = [
    "ArtifactGuard",
    "BranchGuard",
    "GovernanceGuard",
    "Governance",
    "GuardRunner",
    "GuardVerdict",
    "HookDecision",
    "IntegrityCheckResult",
    "IntegrityGate",
    "IntegrityGateResult",
    "ScopeGuard",
    "ViolationType",
]
