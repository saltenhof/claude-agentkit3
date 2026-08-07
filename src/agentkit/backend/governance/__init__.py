"""Governance module -- guards, integrity gates, and policy enforcement.

The package root re-exports the governance VOCABULARY (guard protocols, verdicts,
integrity-gate results) and the guards themselves.

It deliberately does NOT re-export the hook dispatch (``GuardRunner``,
``HookDecision``, ``run_hook``) or the core administration surface
(``Governance``). Both are reached through their owning module:

* ``agentkit.backend.governance.runner`` -- hook dispatch, runs in the
  short-lived hook process on the developer machine (edge);
* ``agentkit.backend.governance.administration`` -- lock deactivation, holds the
  canonical lock repository (core).

AG3-239: re-exporting the edge dispatcher from the core package root made every
importer of ``agentkit.backend.governance`` an importer of the hook process, and
it was a second import path for symbols that already have an owner (CLAUDE.md,
KEINE KOMPATIBILITAETSSCHICHTEN). The facade is removed, not deprecated.
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

__all__ = [
    "ArtifactGuard",
    "BranchGuard",
    "GovernanceGuard",
    "GuardVerdict",
    "DimensionResult",
    "IntegrityDimension",
    "IntegrityGate",
    "IntegrityGateResult",
    "IntegrityGateStatus",
    "ScopeGuard",
    "ViolationType",
]
