"""Integration-stabilization BC — manifest, approval, budget, gate, overlay.

Bounded Context: integration-stabilization (FK-05 §5.2–§5.14, FK-37 §37.1.3).

Implements the full contract machinery for ``implementation_contract =
integration_stabilization``:

- Typed manifest and approval-record models (AC1)
- Fail-closed approval preconditions at all five enforcement points (AC2)
- Repo-set boundary enforcement (AC3)
- Stabilization-budget hard caps (AC4)
- ``stability_gate`` Verify-Stage entry (AC5)
- ``declared_surfaces_only`` Layer-1 deterministic check (AC6)
- ``seam_allowlist`` guard-overlay (AC7)
- Exploration-mandatory routing extension (AC8)
- Closure precondition (AC9)
- Reclassification / no-retroactive-legalization (AC10)
- Telemetry events (AC11)
- Four FK-37 §37.1.3 named checks (AC12)
"""

from __future__ import annotations

from agentkit.backend.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudget,
    StabilizationBudgetCaps,
)

__all__ = [
    "IntegrationScopeManifest",
    "ManifestApprovalRecord",
    "StabilizationBudget",
    "StabilizationBudgetCaps",
]
