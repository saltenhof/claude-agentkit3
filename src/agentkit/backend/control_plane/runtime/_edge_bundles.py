"""ProjectEdge bundle and operating-mode projection helpers."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Literal, cast

from agentkit.backend.control_plane import (
    runtime_constants,
)
from agentkit.backend.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.backend.control_plane.ownership import (
    MIN_BINDING_VERSION,
    canonical_binding_revocation_reason,
)

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.backend.control_plane.records import SessionRunBindingRecord
    from agentkit.backend.core_types.operating_mode import OperatingMode
    from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord

logger = logging.getLogger(__name__)

def _build_fast_edge_bundle(
    *,
    project_key: str,
    sync_class: runtime_constants.FreshnessClass,
    now: datetime,
) -> EdgeBundle:
    """Build an ``ai_augmented`` bundle for a fast story (AG3-018 AC3/AC5).

    A fast story carries no story-scoped session binding and no
    ``story_execution`` / ``qa_artifact_write`` lock. The resulting bundle has
    ``session is None`` and ``lock is None``, so the local edge resolves to
    ``ai_augmented`` and only the baseline guards run.

    Args:
        project_key: The project key for the edge pointer.
        sync_class: Freshness class driving the pointer ``sync_after``.
        now: The mutation timestamp.

    Returns:
        An ``EdgeBundle`` with no session and no locks.
    """
    export_version = f"edge-{uuid.uuid4().hex}"
    pointer = EdgePointer(
        project_key=project_key,
        export_version=export_version,
        operating_mode="ai_augmented",
        bundle_dir=f"_temp/governance/bundles/{export_version}",
        sync_after=now + runtime_constants.SYNC_AFTER_BY_CLASS[sync_class],
        freshness_class=sync_class,
        generated_at=now,
    )
    return EdgeBundle(
        current=pointer,
        session=None,
        lock=None,
        qa_lock=None,
        tombstone_worktree_roots=[],
    )


def _build_edge_bundle(
    *,
    binding: SessionRunBindingRecord | None,
    lock: StoryExecutionLockRecord,
    qa_lock: StoryExecutionLockRecord | None = None,
    sync_class: runtime_constants.FreshnessClass,
    now: datetime,
    tombstone_worktree_roots: tuple[str, ...] = (),
    new_owner_ref: str | None = None,
) -> EdgeBundle:
    operating_mode = _resolve_operating_mode(binding=binding, lock=lock)
    export_version = f"edge-{uuid.uuid4().hex}"
    pointer = EdgePointer(
        project_key=lock.project_key or (binding.project_key if binding else ""),
        export_version=export_version,
        operating_mode=operating_mode,
        bundle_dir=f"_temp/governance/bundles/{export_version}",
        sync_after=now + runtime_constants.SYNC_AFTER_BY_CLASS[sync_class],
        freshness_class=sync_class,
        generated_at=now,
    )
    bundle_revocation_reason = binding.revocation_reason if binding is not None else None
    if binding is not None and binding.status == "revoked":
        bundle_revocation_reason = (
            canonical_binding_revocation_reason(binding.revocation_reason)
            or "session_binding_mismatch"
        )
    binding_view = (
        SessionRunBindingView(
            session_id=binding.session_id,
            project_key=binding.project_key,
            story_id=binding.story_id,
            run_id=binding.run_id,
            principal_type=binding.principal_type,
            worktree_roots=list(binding.worktree_roots),
            binding_version=binding.binding_version,
            operating_mode=operating_mode,
            #: AG3-142 (SOLL-034 behavior part): a revoked binding's status +
            #: machine-readable reason (e.g. ``ownership_transferred``) is
            #: materialized into the bundle instead of vanishing, so the edge
            #: resolve() can surface deterministic ``binding_invalid`` (FK-56
            #: §56.7a) rather than silently falling back to ``ai_augmented``.
            status=binding.status,
            revocation_reason=bundle_revocation_reason,
            new_owner_ref=new_owner_ref,
        )
        if binding is not None
        else None
    )
    lock_view = StoryExecutionLockView(
        project_key=lock.project_key,
        story_id=lock.story_id,
        run_id=lock.run_id,
        lock_type=lock.lock_type,
        status=cast("Literal['ACTIVE', 'INACTIVE', 'INVALID']", lock.status),
        worktree_roots=list(lock.worktree_roots),
        binding_version=lock.binding_version,
        activated_at=lock.activated_at,
        updated_at=lock.updated_at,
        deactivated_at=lock.deactivated_at,
    )
    qa_lock_view = (
        StoryExecutionLockView(
            project_key=qa_lock.project_key,
            story_id=qa_lock.story_id,
            run_id=qa_lock.run_id,
            lock_type=qa_lock.lock_type,
            status=cast("Literal['ACTIVE', 'INACTIVE', 'INVALID']", qa_lock.status),
            worktree_roots=list(qa_lock.worktree_roots),
            binding_version=qa_lock.binding_version,
            activated_at=qa_lock.activated_at,
            updated_at=qa_lock.updated_at,
            deactivated_at=qa_lock.deactivated_at,
        )
        if qa_lock is not None
        else None
    )
    return EdgeBundle(
        current=pointer,
        session=binding_view,
        lock=lock_view,
        qa_lock=qa_lock_view,
        tombstone_worktree_roots=list(tombstone_worktree_roots),
    )


def _resolve_operating_mode(
    *,
    binding: SessionRunBindingRecord | None,
    lock: StoryExecutionLockRecord,
) -> OperatingMode:
    if binding is None:
        return "ai_augmented"
    #: AG3-142 (SOLL-034 behavior, FK-56 §56.7a): the server-side binding
    #: resolution mirrors the edge's own ``ProjectEdgeResolver.resolve()`` --
    #: a revoked binding is deterministically ``binding_invalid`` regardless
    #: of the lock's status, never re-classified as ``story_execution``.
    if binding.status == "revoked":
        return "binding_invalid"
    if lock.status == "ACTIVE":
        return "story_execution"
    return "binding_invalid"

def _next_binding_version(previous_version: str | None) -> str:
    """Mint the next binding version (FK-17 §17.3a.16: monotone Integer >= 1).

    DB-monotone, process-independent (CAS-capable, FK-56 §56.13a): the value is
    derived from the affected binding's PREVIOUSLY PERSISTED version (``previous
    + 1``), or the initial :data:`MIN_BINDING_VERSION` when no binding exists
    yet. There is deliberately NO wall clock and NO process-local counter — the
    former ``bind-<uuid4>`` token was non-monotone, and a clock-derived token
    both leaks a wall-clock dependency into ownership/takeover challenge material
    and is only process-local monotone, neither of which is a sound CAS
    foundation.

    The caller reads ``previous_version`` from the store at the persistence
    boundary of the SAME mutation whose atomic commit (ownership CAS at
    start-phase finalize / run-scoped binding upsert) serialises the write, so no
    NEW fencing/lock is introduced (AG3-137 is a pure value-domain change; the
    fence lives in AG3-142).

    Representation note (AG3-137 scope §5): the returned value is a canonical
    decimal ``str`` because it flows verbatim into the derived
    ``StoryExecutionLockRecord`` / edge-bundle projections whose column lives in
    ``sqlite_store`` (K5: not migrated here); a literal numeric-column migration
    is deferred to AG3-142. Only the value DOMAIN is a monotone positive integer.

    Args:
        previous_version: The affected binding's currently persisted
            ``binding_version`` (a canonical integer string), or ``None`` when no
            binding exists yet for the target session.

    Returns:
        The next canonical decimal version string.
    """
    if previous_version is None:
        return str(MIN_BINDING_VERSION)
    return str(int(previous_version) + 1)
