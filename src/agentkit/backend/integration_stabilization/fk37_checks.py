"""The four FK-37 §37.1.3 named fail-closed checks for integration_stabilization.

AC12: Four named, individually testable, fail-closed checks:
- ``integration_target_matrix_passed``      → Layer 4 / QA-subflow + closure
- ``declared_surfaces_only``                → Layer 1 / structural
- ``stabilization_budget_not_exhausted``    → hook/capability primary + audit in QA
- ``stability_gate``                        → Layer 4 / QA-subflow + closure

Plus the two additional named fail-closed preconditions (AC12):
- ``manifest_approval_required``            → Layer 1 / precondition
- ``binding_integrity``                     → Layer 1 / precondition

Each function returns a named, typed result. All checks are deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.integration_stabilization.declared_surfaces_check import (
    DeclaredSurfacesCheckResult,
    check_declared_surfaces_only,
)
from agentkit.backend.integration_stabilization.preconditions import (
    ApprovalCheckResult,
    BindingIntegrityCheckResult,
    BudgetCheckResult,
    check_approval_present,
    check_binding_integrity,
    check_budget_not_exhausted,
)

if TYPE_CHECKING:
    from agentkit.backend.integration_stabilization.models import (
        IntegrationScopeManifest,
        ManifestApprovalRecord,
        StabilizationBudget,
    )

__all__ = [
    "FK37CheckName",
    "IntegrationTargetMatrixResult",
    "StabilityGateResult",
    "check_fk37_integration_target_matrix_passed",
    "check_fk37_declared_surfaces_only",
    "check_fk37_stabilization_budget_not_exhausted",
    "check_fk37_stability_gate",
    "check_fk37_manifest_approval_required",
    "check_fk37_binding_integrity",
    "ApprovalCheckResult",
    "BindingIntegrityCheckResult",
    "BudgetCheckResult",
    "DeclaredSurfacesCheckResult",
]


class FK37CheckName:
    """Canonical wire-key names for the four FK-37 §37.1.3 checks (ARCH-55)."""

    INTEGRATION_TARGET_MATRIX_PASSED: str = "integration_target_matrix_passed"
    DECLARED_SURFACES_ONLY: str = "declared_surfaces_only"
    STABILIZATION_BUDGET_NOT_EXHAUSTED: str = "stabilization_budget_not_exhausted"
    STABILITY_GATE: str = "stability_gate"
    # Additional named preconditions (AC12)
    MANIFEST_APPROVAL_REQUIRED: str = "manifest_approval_required"
    BINDING_INTEGRITY: str = "binding_integrity"


@dataclass(frozen=True)
class IntegrationTargetMatrixResult:
    """Result of the integration_target_matrix_passed check.

    Attributes:
        passed: True iff all declared integration targets are achieved.
        unmet_targets: Names of targets not yet achieved.
    """

    passed: bool
    unmet_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class StabilityGateResult:
    """Aggregate result of the stability_gate (wraps all four FK-37 checks).

    Attributes:
        passed: True iff ALL four FK-37 checks pass.
        check_name: The canonical check name (``stability_gate``).
        declared_surfaces_result: Result of the declared_surfaces_only check.
        budget_result: Result of the budget_not_exhausted check.
        target_matrix_result: Result of the target_matrix_passed check.
        approval_result: Result of the manifest_approval_required check.
        binding_result: Result of the binding_integrity check.
        block_reasons: All blocking reasons from failed checks.
    """

    passed: bool
    check_name: str = FK37CheckName.STABILITY_GATE
    declared_surfaces_result: DeclaredSurfacesCheckResult | None = None
    budget_result: BudgetCheckResult | None = None
    target_matrix_result: IntegrationTargetMatrixResult | None = None
    approval_result: ApprovalCheckResult | None = None
    binding_result: BindingIntegrityCheckResult | None = None
    block_reasons: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Individual FK-37 §37.1.3 check functions
# ---------------------------------------------------------------------------


def check_fk37_manifest_approval_required(
    approval_record: ManifestApprovalRecord | None,
) -> ApprovalCheckResult:
    """Named fail-closed precondition: manifest_approval_required (AC12).

    Layer 1 / precondition. Must pass before any productive work is allowed.

    Args:
        approval_record: The current approval record, or ``None`` if absent.

    Returns:
        An ``ApprovalCheckResult`` (PASS or BLOCK).
    """
    return check_approval_present(approval_record)


def check_fk37_binding_integrity(
    manifest: IntegrationScopeManifest,
    approval_record: ManifestApprovalRecord,
    *,
    current_run_id: str,
) -> BindingIntegrityCheckResult:
    """Named fail-closed precondition: binding_integrity (AC12).

    Layer 1 / precondition. Verifies hash/version/run match.

    Args:
        manifest: The active integration scope manifest.
        approval_record: The approval record to verify against.
        current_run_id: The current pipeline run identifier.

    Returns:
        A ``BindingIntegrityCheckResult`` (PASS or BLOCK).
    """
    return check_binding_integrity(
        manifest, approval_record, current_run_id=current_run_id
    )


def check_fk37_declared_surfaces_only(
    *,
    touched_paths: tuple[str, ...],
    manifest: IntegrationScopeManifest,
    seam_allowlist: tuple[str, ...] | None = None,
) -> DeclaredSurfacesCheckResult:
    """FK-37 §37.1.3 check: declared_surfaces_only (Layer 1).

    Deterministic structural check. No LLM path.
    Invariant: declared_surfaces_only_is_deterministic.

    Args:
        touched_paths: Paths actually touched in the diff.
        manifest: The active integration scope manifest.
        seam_allowlist: Optional materialized seam allowlist.

    Returns:
        A ``DeclaredSurfacesCheckResult`` (PASS or BLOCK).
    """
    return check_declared_surfaces_only(
        touched_paths=touched_paths,
        manifest=manifest,
        seam_allowlist=seam_allowlist,
    )


def check_fk37_stabilization_budget_not_exhausted(
    budget: StabilizationBudget,
) -> BudgetCheckResult:
    """FK-37 §37.1.3 check: stabilization_budget_not_exhausted.

    Primary: hook/capability layer (live-blocking before next step).
    Also audited in QA-subflow per FK-37 §37.1.3.
    Invariant: budget_exhaustion_blocks_live_capability.

    Args:
        budget: The current live stabilization budget.

    Returns:
        A ``BudgetCheckResult`` (PASS or BLOCK).
    """
    return check_budget_not_exhausted(budget)


def check_fk37_integration_target_matrix_passed(
    *,
    achieved_targets: frozenset[str],
    required_targets: frozenset[str],
) -> IntegrationTargetMatrixResult:
    """FK-37 §37.1.3 check: integration_target_matrix_passed (Layer 4).

    QA-subflow / closure precondition. All declared integration targets must
    be achieved.

    Args:
        achieved_targets: Set of integration target names that have passed.
        required_targets: Set of integration target names declared in the
            manifest (all must be achieved for PASS).

    Returns:
        An ``IntegrationTargetMatrixResult`` (PASS or BLOCK).
    """
    unmet = required_targets - achieved_targets
    if unmet:
        return IntegrationTargetMatrixResult(
            passed=False,
            unmet_targets=tuple(sorted(unmet)),
        )
    return IntegrationTargetMatrixResult(passed=True)


def check_fk37_stability_gate(
    *,
    touched_paths: tuple[str, ...],
    manifest: IntegrationScopeManifest,
    budget: StabilizationBudget,
    achieved_targets: frozenset[str],
    approval_record: ManifestApprovalRecord | None,
    current_run_id: str,
    seam_allowlist: tuple[str, ...] | None = None,
) -> StabilityGateResult:
    """FK-37 §37.1.3 stability_gate: aggregate of all four checks (Layer 4).

    This is the dedicated Verify-Stage registered in the AG3-064 registry as
    ``stability_gate`` (AC5). It wraps all four FK-37 §37.1.3 checks plus the
    two named preconditions (AC12). FAIL on:
    - undeclared_surface (declared_surfaces_only FAIL)
    - unmet integration_targets (integration_target_matrix_passed FAIL)
    - budget breach (stabilization_budget_not_exhausted FAIL)
    - missing/mismatched approval (manifest_approval_required / binding_integrity FAIL)

    Args:
        touched_paths: Paths actually touched in the diff.
        manifest: The active integration scope manifest.
        budget: The current live stabilization budget.
        achieved_targets: Set of integration target names that have passed.
        approval_record: The current approval record (``None`` = not yet approved).
        current_run_id: The current pipeline run identifier.
        seam_allowlist: Optional materialized seam allowlist.

    Returns:
        A ``StabilityGateResult`` with aggregate PASS/FAIL.
    """
    block_reasons: list[str] = []
    required_targets = frozenset(manifest.integration_targets)

    approval_result = check_fk37_manifest_approval_required(approval_record)
    if not approval_result.approved:
        block_reasons.append(f"[manifest_approval_required] {approval_result.reason}")

    binding_result: BindingIntegrityCheckResult | None = None
    if approval_record is not None:
        binding_result = check_fk37_binding_integrity(
            manifest, approval_record, current_run_id=current_run_id
        )
        if not binding_result.binding_valid:
            block_reasons.append(f"[binding_integrity] {binding_result.reason}")

    declared_result = check_fk37_declared_surfaces_only(
        touched_paths=touched_paths,
        manifest=manifest,
        seam_allowlist=seam_allowlist,
    )
    if not declared_result.passed:
        for finding in declared_result.findings:
            block_reasons.append(f"[declared_surfaces_only] {finding.message}")

    budget_result = check_fk37_stabilization_budget_not_exhausted(budget)
    if not budget_result.within_budget:
        block_reasons.append(
            f"[stabilization_budget_not_exhausted] exhausted caps: "
            f"{list(budget_result.exhausted_caps)}"
        )

    target_result = check_fk37_integration_target_matrix_passed(
        achieved_targets=achieved_targets,
        required_targets=required_targets,
    )
    if not target_result.passed:
        block_reasons.append(
            f"[integration_target_matrix_passed] unmet targets: "
            f"{list(target_result.unmet_targets)}"
        )

    overall_passed = len(block_reasons) == 0
    return StabilityGateResult(
        passed=overall_passed,
        declared_surfaces_result=declared_result,
        budget_result=budget_result,
        target_matrix_result=target_result,
        approval_result=approval_result,
        binding_result=binding_result,
        block_reasons=tuple(block_reasons),
    )
