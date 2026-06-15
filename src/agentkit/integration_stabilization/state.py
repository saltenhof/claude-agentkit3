"""Persistence helpers for integration-stabilization runtime state.

Provides load/save functions for the IntegrationScopeManifest and
ManifestApprovalRecord that are persisted to the story directory during a
pipeline run. These are the SINGLE SOURCE OF TRUTH for IS runtime state
in the story directory (FK-05 §5.5.2/§5.5.4, SSOT principle).

File layout under ``story_dir``:
- ``integration_manifest.json``   — the approved IntegrationScopeManifest
- ``integration_approval.json``   — the ManifestApprovalRecord
- ``integration_quarantine.json`` — pre-snapshot quarantine state
  (written at reclassification, FK-05 §5.7/§5.13)

These files are written once the manifest is approved and read by:
- The StructuralChecker IS stages (declared_surfaces_only, budget, approval)
- The ClosurePhaseHandler IS precondition check
- The SeamAllowlistGuard (via the manifest)
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003  -- Path used in runtime path operations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.integration_stabilization.models import (
        IntegrationScopeManifest,
        ManifestApprovalRecord,
    )
    from agentkit.integration_stabilization.preconditions import (
        ReclassificationCheckResult,
    )
    from agentkit.telemetry.emitters import EventEmitter

__all__ = [
    "IS_MANIFEST_FILE",
    "IS_APPROVAL_FILE",
    "IS_QUARANTINE_FILE",
    "RepoSetViolationError",
    "approve_manifest",
    "load_integration_manifest",
    "load_manifest_approval",
    "read_quarantine_state",
    "save_integration_manifest",
    "save_manifest_approval",
    "apply_reclassification_no_retroactive_legalization",
]


def read_quarantine_state(story_dir: Path) -> tuple[str, ...]:
    """Read the persisted pre-snapshot quarantined deltas (FK-05 §5.7/§5.13).

    Returns the quarantined pre-snapshot cross-scope delta identifiers written
    by :func:`apply_reclassification_no_retroactive_legalization` at the
    reclassification snapshot boundary. These deltas are NOT legalized by the IS
    contract; downstream checks (declared_surfaces_only / closure) READ this
    state so a pre-snapshot delta stays quarantined (invariant
    ``reclassification_may_not_legalize_pre_manifest_cross_scope_delta``).

    Args:
        story_dir: The story working directory.

    Returns:
        The quarantined delta identifiers, or an empty tuple when none persisted.
    """
    quarantine_path = story_dir / IS_QUARANTINE_FILE
    if not quarantine_path.exists():
        return ()
    try:
        data = json.loads(quarantine_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    raw = data.get("pre_snapshot_deltas") if isinstance(data, dict) else None
    if isinstance(raw, list):
        return tuple(str(d) for d in raw)
    return ()


class RepoSetViolationError(ValueError):
    """Raised when a manifest authorizes paths outside the bound worktree set.

    FK-05 §5.5.5 / invariant ``manifest_may_not_expand_repo_set``: persisting or
    approving such a manifest is fail-closed forbidden (ERROR F / AC3).
    """

#: Canonical filename for the persisted IntegrationScopeManifest.
IS_MANIFEST_FILE: str = "integration_manifest.json"

#: Canonical filename for the persisted ManifestApprovalRecord.
IS_APPROVAL_FILE: str = "integration_approval.json"

#: Canonical filename for the persisted reclassification quarantine state.
IS_QUARANTINE_FILE: str = "integration_quarantine.json"


def load_integration_manifest(
    story_dir: Path,
) -> IntegrationScopeManifest | None:
    """Load the IntegrationScopeManifest from the story directory.

    Returns ``None`` if no manifest file is present (not yet approved).
    The content_hash is recomputed on load so a tampered/stale file is
    detected (fail-closed: the hash mismatch will surface in binding checks).

    Args:
        story_dir: The story working directory.

    Returns:
        The loaded manifest, or ``None`` if no file is present.
    """
    from agentkit.integration_stabilization.models import IntegrationScopeManifest

    manifest_path = story_dir / IS_MANIFEST_FILE
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Force hash recomputation by removing the stored hash so the
        # model validator recomputes it fresh (tamper detection).
        data.pop("content_hash", None)
        return IntegrationScopeManifest(**data)
    except Exception:  # noqa: BLE001
        return None


def load_manifest_approval(
    story_dir: Path,
) -> ManifestApprovalRecord | None:
    """Load the ManifestApprovalRecord from the story directory.

    Returns ``None`` if no approval file is present.

    Args:
        story_dir: The story working directory.

    Returns:
        The loaded approval record, or ``None`` if no file is present.
    """
    from agentkit.integration_stabilization.models import ManifestApprovalRecord

    approval_path = story_dir / IS_APPROVAL_FILE
    if not approval_path.exists():
        return None
    try:
        data = json.loads(approval_path.read_text(encoding="utf-8"))
        return ManifestApprovalRecord(**data)
    except Exception:  # noqa: BLE001
        return None


def save_integration_manifest(
    story_dir: Path,
    manifest: IntegrationScopeManifest,
    *,
    bound_roots: tuple[str, ...] | None = None,
) -> None:
    """Persist the IntegrationScopeManifest to the story directory.

    AC1 / FK-71 design justification -- raw Pydantic JSON vs. ArtifactEnvelope:
    The manifest is DOMAIN STATE persisted once per story lifecycle (written at
    approval, read by guards/structural checks/closure). The ArtifactEnvelope
    mechanism (FK-71 §71.2) is designed for QA-layer artifacts (structural.json,
    qa_review.json, decision.json) which carry ``stage``, ``attempt``, producer
    timestamps and pass through the ArtifactManager write path. Those fields have
    no meaning for a singleton domain-state object. Using
    ``IntegrationScopeManifest.model_dump_json()`` is the concept-conform storage
    pattern for typed domain state (same as ``StoryContext``, ``FlowExecution``,
    ``PhaseSnapshot`` in the state_backend). The manifest IS typed (Pydantic,
    frozen, hash-validated) and has a clear producer (the approval boundary in
    ``approve_manifest``). Adding an ArtifactEnvelope wrapper would add FK-71
    QA-artifact machinery to a domain-state object without a supporting concept --
    that is FIX THE MODEL, NOT THE SYMPTOM in reverse.

    AG3-069 (ERROR F / AC3, FK-05 §5.5.5): when ``bound_roots`` is supplied the
    repo-set boundary is enforced fail-closed BEFORE the file is written -- a
    manifest whose ``allowed_repos_paths`` or ``target_seams`` escape the bound
    worktrees is rejected with :class:`RepoSetViolationError` (the invariant
    ``manifest_may_not_expand_repo_set``). ``None`` keeps the low-level write for
    callers that have already validated the repo set (e.g. fixtures / tests).

    Args:
        story_dir: The story working directory.
        manifest: The manifest to persist.
        bound_roots: The already-bound worktree roots; when given, the repo-set
            boundary is enforced before persisting.

    Raises:
        RepoSetViolationError: When ``bound_roots`` is given and a manifest path
            escapes the bound worktrees.
    """
    if bound_roots is not None:
        _enforce_repo_set(manifest, bound_roots)
    manifest_path = story_dir / IS_MANIFEST_FILE
    manifest_path.write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _enforce_repo_set(
    manifest: IntegrationScopeManifest,
    bound_roots: tuple[str, ...],
) -> None:
    """Raise :class:`RepoSetViolationError` if the manifest escapes ``bound_roots``."""
    from agentkit.integration_stabilization.preconditions import (
        check_manifest_repo_set,
    )

    repo_set = check_manifest_repo_set(manifest, bound_roots=bound_roots)
    if not repo_set.within_bounds:
        raise RepoSetViolationError(
            "IntegrationScopeManifest authorizes paths outside the bound "
            f"worktree set: {list(repo_set.violating_paths)} (FK-05 §5.5.5, AC3, "
            "invariant: manifest_may_not_expand_repo_set)."
        )


def save_manifest_approval(
    story_dir: Path,
    approval: ManifestApprovalRecord,
) -> None:
    """Persist the ManifestApprovalRecord to the story directory.

    AC1 / FK-71 design justification -- raw Pydantic JSON vs. ArtifactEnvelope:
    See :func:`save_integration_manifest` for the full rationale. The approval
    record is domain state (singleton, lifecycle-bound) and uses the same
    Pydantic ``model_dump_json()`` persistence pattern as other typed domain-state
    objects. It is NOT a QA-layer artifact and must NOT be wrapped in an
    ArtifactEnvelope (FK-71 §71.2 is for QA-subflow outputs, not approval records).

    This is the boundary where the approval is durably written. Callers that
    have access to a telemetry emitter should emit the
    ``integration_manifest_approved`` event (via
    :func:`agentkit.integration_stabilization.events.emit_integration_manifest_approved`)
    immediately after calling this function (AC11 / FK-05 §5.14).

    Args:
        story_dir: The story working directory.
        approval: The approval record to persist.
    """
    approval_path = story_dir / IS_APPROVAL_FILE
    approval_path.write_text(
        approval.model_dump_json(indent=2),
        encoding="utf-8",
    )


def approve_manifest(
    story_dir: Path,
    manifest: IntegrationScopeManifest,
    approval: ManifestApprovalRecord,
    *,
    bound_roots: tuple[str, ...],
    current_run_id: str,
    emitter: EventEmitter | None = None,
) -> None:
    """Approve + persist an IS manifest at the single fail-closed boundary (AC3/AC11).

    This is THE manifest-approval boundary (FK-05 §5.5.4/§5.5.5):

    1. enforce the repo-set boundary (``target_seams`` + ``allowed_repos_paths``
       inside ``bound_roots``) — fail-closed (:class:`RepoSetViolationError`);
    2. enforce binding integrity (hash/version/project/story/run match) —
       fail-closed (:class:`ValueError`);
    3. persist the manifest AND the approval record;
    4. emit the ``integration_manifest_approved`` telemetry event through the
       real emitter at the approval boundary (AC11, FK-05 §5.14).

    Args:
        story_dir: The story working directory.
        manifest: The manifest to approve and persist.
        approval: The attested approval record.
        bound_roots: The already-bound worktree roots (repo-set boundary).
        current_run_id: The active run id (binding-integrity check).
        emitter: Optional telemetry emitter; the approval event is emitted on
            success. ``None`` => no emission.

    Raises:
        RepoSetViolationError: When the manifest escapes the bound worktrees.
        ValueError: When the approval does not bind the manifest / run.
    """
    from agentkit.integration_stabilization.preconditions import (
        check_binding_integrity,
    )

    _enforce_repo_set(manifest, bound_roots)
    binding = check_binding_integrity(manifest, approval, current_run_id=current_run_id)
    if not binding.binding_valid:
        raise ValueError(
            "ManifestApprovalRecord does not bind the manifest fail-closed: "
            f"{binding.reason} (FK-05 §5.5.4, AC2)."
        )

    save_integration_manifest(story_dir, manifest)
    save_manifest_approval(story_dir, approval)

    if emitter is not None:
        from agentkit.integration_stabilization.events import (
            emit_integration_manifest_approved,
        )

        emitter.emit(
            emit_integration_manifest_approved(
                story_id=manifest.story_id,
                project_key=manifest.project_key,
                run_id=current_run_id,
                manifest_version=manifest.version,
                manifest_hash=manifest.content_hash,
            )
        )


def apply_reclassification_no_retroactive_legalization(
    story_dir: Path,
    *,
    pre_snapshot_deltas: tuple[str, ...],
) -> ReclassificationCheckResult:
    """Apply the no-retroactive-legalization rule at reclassification (FK-05 §5.7/§5.13).

    Creates a fresh ``evidence_epoch`` (UUID4 + timestamp) at the manifest
    snapshot boundary and persists the quarantine state to ``story_dir``.
    Pre-snapshot cross-scope deltas are quarantined (NOT legalized) — the
    fresh epoch marks the start of the new IS contract scope.

    Invariant: reclassification_may_not_legalize_pre_manifest_cross_scope_delta.

    Args:
        story_dir: The story working directory.
        pre_snapshot_deltas: Identifiers/descriptors of cross-scope deltas
            that existed before the manifest snapshot boundary.

    Returns:
        A :class:`~agentkit.integration_stabilization.preconditions.ReclassificationCheckResult`
        with ``legalization_blocked=True`` and the fresh epoch. The quarantine
        state is persisted to ``story_dir/integration_quarantine.json``.
    """
    from agentkit.integration_stabilization.preconditions import (
        check_reclassification_no_retroactive_legalization,
    )

    # Generate a fresh evidence_epoch at the reclassification boundary.
    epoch = f"{datetime.now(UTC).isoformat()}_{uuid.uuid4().hex[:8]}"

    # Persist the quarantine state so it can be read back by the structural
    # checker / closure precondition in subsequent pipeline steps.
    quarantine_data = {
        "evidence_epoch": epoch,
        "pre_snapshot_deltas": list(pre_snapshot_deltas),
        "reclassified_at": datetime.now(UTC).isoformat(),
        "legalization_blocked": True,
    }
    quarantine_path = story_dir / IS_QUARANTINE_FILE
    quarantine_path.write_text(
        json.dumps(quarantine_data, indent=2),
        encoding="utf-8",
    )

    return check_reclassification_no_retroactive_legalization(
        pre_snapshot_deltas=pre_snapshot_deltas,
        evidence_epoch=epoch,
    )
