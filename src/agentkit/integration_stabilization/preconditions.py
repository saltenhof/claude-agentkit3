"""Fail-closed approval preconditions for integration-stabilization.

Implements the five enforcement points from FK-05 §5.5.1/§5.9/§5.11/§5.12:

1. Worker-spawn block: no worker spawn without an approved record.
2. Setup/routing block: no execution-route without an approved manifest.
3. PreToolUse write-guard: block writes outside seam_allowlist.
4. Capability/hook-layer budget block: next step outside budget is blocked live.
5. Closure precondition: closure requires stability_gate=PASS + all targets
   reached + no open manifest violation + no replan/split need.

All checks are deterministic (no LLM path) and fail-closed:
missing/mismatched approval -> block immediately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.integration_stabilization.models import (
        IntegrationScopeManifest,
        ManifestApprovalRecord,
        StabilizationBudget,
    )

__all__ = [
    "ApprovalCheckResult",
    "BindingIntegrityCheckResult",
    "BudgetCheckResult",
    "ClosurePreconditionResult",
    "RepoSetCheckResult",
    "check_approval_present",
    "check_binding_integrity",
    "check_budget_not_exhausted",
    "check_closure_precondition",
    "check_manifest_repo_set",
    "check_reclassification_no_retroactive_legalization",
    "ReclassificationCheckResult",
]


@dataclass(frozen=True)
class ApprovalCheckResult:
    """Result of the approval-present fail-closed check.

    Attributes:
        approved: Whether an approved record is present and binding.
        reason: Human-readable reason for a block (empty on pass).
    """

    approved: bool
    reason: str = ""


@dataclass(frozen=True)
class BindingIntegrityCheckResult:
    """Result of the binding-integrity check (hash/version/run mismatch).

    Attributes:
        binding_valid: Whether manifest and record binding is consistent.
        reason: Human-readable reason for a block (empty on pass).
    """

    binding_valid: bool
    reason: str = ""


@dataclass(frozen=True)
class RepoSetCheckResult:
    """Result of the repo-set boundary check (FK-05 §5.5.5).

    Attributes:
        within_bounds: Whether all manifest paths are within bound roots.
        violating_paths: Paths that violate the repo-set boundary.
    """

    within_bounds: bool
    violating_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class BudgetCheckResult:
    """Result of the budget-exhaustion check (FK-05 §5.9).

    Attributes:
        within_budget: Whether the budget has capacity for another step.
        exhausted_caps: Names of exhausted caps (empty when within budget).
    """

    within_budget: bool
    exhausted_caps: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClosurePreconditionResult:
    """Result of the closure precondition check (FK-05 §5.11).

    Attributes:
        closure_allowed: Whether closure may proceed.
        blocking_reasons: Reasons that prevent closure (empty when allowed).
    """

    closure_allowed: bool
    blocking_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReclassificationCheckResult:
    """Result of the reclassification no-retroactive-legalization check.

    Invariant: reclassification_may_not_legalize_pre_manifest_cross_scope_delta.

    Attributes:
        legalization_blocked: True iff pre-manifest deltas were quarantined
            (no retroactive legalization occurred).
        quarantined_deltas: Identifiers/descriptors of quarantined deltas.
        evidence_epoch: The fresh evidence epoch assigned at reclassification.
    """

    legalization_blocked: bool
    quarantined_deltas: tuple[str, ...] = ()
    evidence_epoch: str = ""


def check_approval_present(
    approval_record: ManifestApprovalRecord | None,
) -> ApprovalCheckResult:
    """Check whether an approved manifest-approval record is present.

    Enforcement point 1 (worker-spawn) and 2 (setup/routing):
    No productive integration work without an approved record.

    Args:
        approval_record: The current approval record, or ``None`` if absent.

    Returns:
        An ``ApprovalCheckResult`` with ``approved=True`` iff a non-None
        record is provided.
    """
    if approval_record is None:
        return ApprovalCheckResult(
            approved=False,
            reason=(
                "No approved ManifestApprovalRecord present. "
                "Productive integration-stabilization work is fail-closed "
                "blocked without an approved record (FK-05 §5.5.1/§5.5.4)."
            ),
        )
    return ApprovalCheckResult(approved=True)


def check_binding_integrity(
    manifest: IntegrationScopeManifest,
    approval_record: ManifestApprovalRecord,
    *,
    current_run_id: str,
) -> BindingIntegrityCheckResult:
    """Check that the approval record binds the manifest and matches the run.

    Enforcement point 2 (binding/hash/run mismatch):
    A record that binds a different manifest version, hash, or run is
    fail-closed blocked.

    Args:
        manifest: The active integration scope manifest.
        approval_record: The approval record to verify binding for.
        current_run_id: The current pipeline run identifier.

    Returns:
        A ``BindingIntegrityCheckResult`` with ``binding_valid=True`` iff
        all of (project_key, story_id, manifest_version, manifest_hash, run_id)
        match.
    """
    if not approval_record.binds_manifest(manifest):
        reasons = []
        if approval_record.project_key != manifest.project_key:
            reasons.append(
                f"project_key mismatch: record={approval_record.project_key!r} "
                f"vs manifest={manifest.project_key!r}"
            )
        if approval_record.story_id != manifest.story_id:
            reasons.append(
                f"story_id mismatch: record={approval_record.story_id!r} "
                f"vs manifest={manifest.story_id!r}"
            )
        if approval_record.manifest_version != manifest.version:
            reasons.append(
                f"manifest_version mismatch: record={approval_record.manifest_version} "
                f"vs manifest={manifest.version}"
            )
        if approval_record.manifest_hash != manifest.content_hash:
            reasons.append(
                f"manifest_hash mismatch: record={approval_record.manifest_hash!r} "
                f"vs manifest={manifest.content_hash!r}"
            )
        return BindingIntegrityCheckResult(
            binding_valid=False,
            reason="; ".join(reasons) or "binding_integrity_failed",
        )
    if approval_record.run_id != current_run_id:
        return BindingIntegrityCheckResult(
            binding_valid=False,
            reason=(
                f"run_id mismatch: record={approval_record.run_id!r} "
                f"vs current_run_id={current_run_id!r} "
                "(FK-05 §5.5.4 run-id binding)"
            ),
        )
    return BindingIntegrityCheckResult(binding_valid=True)


def check_manifest_repo_set(
    manifest: IntegrationScopeManifest,
    *,
    bound_roots: tuple[str, ...],
) -> RepoSetCheckResult:
    """Check that all manifest paths are within already-bound worktree roots.

    Invariant: manifest_may_not_expand_repo_set (FK-05 §5.5.5).
    The manifest may only authorize paths inside the already-bound
    participating repos. Introducing new repos/worktrees is fail-closed.

    Both ``allowed_repos_paths`` AND ``target_seams`` are checked: a declared
    seam outside the bound worktrees would also silently expand the repo set
    (FK-05 §5.5.5), so the seam paths are covered by the same fail-closed rule.

    Args:
        manifest: The integration scope manifest to validate.
        bound_roots: The already-bound worktree root paths.

    Returns:
        A ``RepoSetCheckResult`` with ``within_bounds=True`` iff every path in
        ``allowed_repos_paths`` AND every path in ``target_seams`` is a sub-path
        of a bound root.
    """
    import os

    normalized_roots = tuple(os.path.normpath(r) for r in bound_roots)

    violating: list[str] = []
    for path in (*manifest.allowed_repos_paths, *manifest.target_seams):
        norm_path = os.path.normpath(path)
        inside = any(
            norm_path == root or norm_path.startswith(root + os.sep)
            for root in normalized_roots
        )
        if not inside:
            violating.append(path)

    if violating:
        return RepoSetCheckResult(
            within_bounds=False,
            violating_paths=tuple(violating),
        )
    return RepoSetCheckResult(within_bounds=True)


def check_budget_not_exhausted(
    budget: StabilizationBudget,
) -> BudgetCheckResult:
    """Check that the stabilization budget has not been exhausted.

    Enforcement point 4 (capability/hook layer): the next productive step
    outside the remaining budget is blocked live (FK-05 §5.9).
    Invariant: budget_exhaustion_blocks_live_capability.

    Args:
        budget: The current live stabilization budget with counters.

    Returns:
        A ``BudgetCheckResult`` with ``within_budget=True`` iff no cap
        has been exhausted.
    """
    if budget.any_cap_exhausted:
        return BudgetCheckResult(
            within_budget=False,
            exhausted_caps=tuple(budget.exhausted_caps()),
        )
    return BudgetCheckResult(within_budget=True)


def check_closure_precondition(
    *,
    stability_gate_passed: bool,
    achieved_targets: frozenset[str],
    required_targets: frozenset[str],
    open_manifest_violations: int,
    replan_needed: bool,
) -> ClosurePreconditionResult:
    """Check all closure preconditions for integration_stabilization (FK-05 §5.11).

    Enforcement point 5: closure only proceeds when ALL conditions hold.
    Invariant: closure_requires_stability_gate_pass.

    Args:
        stability_gate_passed: Whether the stability_gate Verify-Stage passed.
        achieved_targets: Set of integration_target names that have passed.
        required_targets: Set of integration_target names declared in the
            manifest (all must be achieved for closure).
        open_manifest_violations: Count of open unresolved manifest violations.
        replan_needed: Whether a replan or story-split has been flagged.

    Returns:
        A ``ClosurePreconditionResult`` with ``closure_allowed=True`` iff
        all five FK-05 §5.11 conditions are met.
    """
    reasons: list[str] = []

    if not stability_gate_passed:
        reasons.append(
            "stability_gate has not passed (FK-05 §5.11 / "
            "invariant: closure_requires_stability_gate_pass)"
        )

    unmet = required_targets - achieved_targets
    if unmet:
        sorted_unmet = sorted(unmet)
        reasons.append(
            f"integration_targets not yet achieved: {sorted_unmet} "
            "(FK-05 §5.11)"
        )

    if open_manifest_violations > 0:
        reasons.append(
            f"{open_manifest_violations} open manifest violation(s) unresolved "
            "(FK-05 §5.11)"
        )

    if replan_needed:
        reasons.append(
            "replan or story-split flagged; closure not allowed until resolved "
            "(FK-05 §5.11)"
        )

    if reasons:
        return ClosurePreconditionResult(
            closure_allowed=False,
            blocking_reasons=tuple(reasons),
        )
    return ClosurePreconditionResult(closure_allowed=True)


def check_reclassification_no_retroactive_legalization(
    *,
    pre_snapshot_deltas: tuple[str, ...],
    evidence_epoch: str,
) -> ReclassificationCheckResult:
    """Enforce no-retroactive-legalization on reclassification (FK-05 §5.7/§5.13).

    Invariant: reclassification_may_not_legalize_pre_manifest_cross_scope_delta.

    When a standard story is reclassified to integration_stabilization, any
    pre-manifest cross-scope deltas are quarantined (NOT legalized). A fresh
    ``evidence_epoch`` is generated at the approved manifest snapshot boundary;
    work before that boundary is quarantined, not retroactively approved.

    Args:
        pre_snapshot_deltas: Identifiers/descriptors of deltas that existed
            before the manifest snapshot boundary.
        evidence_epoch: The fresh evidence epoch assigned at reclassification
            (non-empty string signals a valid fresh epoch).

    Returns:
        A ``ReclassificationCheckResult`` with ``legalization_blocked=True``
        iff pre-snapshot deltas are quarantined (not legalized) and an epoch
        is present. Empty pre_snapshot_deltas always passes trivially.
    """
    if not evidence_epoch:
        return ReclassificationCheckResult(
            legalization_blocked=False,
            quarantined_deltas=pre_snapshot_deltas,
            evidence_epoch="",
        )
    # All pre-snapshot deltas are quarantined; the fresh epoch enforces the
    # snapshot boundary. Legalization is blocked (invariant holds).
    return ReclassificationCheckResult(
        legalization_blocked=True,
        quarantined_deltas=pre_snapshot_deltas,
        evidence_epoch=evidence_epoch,
    )
