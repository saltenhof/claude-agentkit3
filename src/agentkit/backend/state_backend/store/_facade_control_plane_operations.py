"""Control-plane operation, inflight idempotency, and repair facade operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.backend.state_backend.store import mappers
from agentkit.backend.state_backend.store._facade_backend import (
    _backend_module,
    _require_control_plane_backend,
)

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.backend.control_plane.records import (
        BindingDeleteScope,
        ControlPlaneOperationRecord,
        RunOwnershipRecord,
        SessionRunBindingRecord,
    )
    from agentkit.backend.governance.guard_system.records import (
        StoryExecutionLockRecord,
    )
    from agentkit.backend.prompt_runtime.execution_contract import (
        ExecutionContractDigestRecord,
    )
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord


_GLOBAL_CP_OP_UNSUPPORTED = "Global control-plane operations are unsupported by the active backend"


def save_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
) -> None:
    backend = _backend_module()
    if not hasattr(backend, "save_control_plane_operation_global_row"):
        raise RuntimeError(
            _GLOBAL_CP_OP_UNSUPPORTED,
        )
    row = mappers.control_plane_op_to_row(record)
    backend.save_control_plane_operation_global_row(row)


def claim_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
) -> bool:
    """Atomically claim an op_id before dispatch (AG3-054 E4).

    Returns ``True`` iff this caller inserted the placeholder row (won the claim);
    ``False`` when the op_id already existed. The win/lose decision is made at the
    backend (``INSERT ... ON CONFLICT DO NOTHING``), so two concurrent callers of
    the same op_id cannot both run the dispatch side effects.
    """
    backend = _backend_module()
    if not hasattr(backend, "claim_control_plane_operation_global_row"):
        raise RuntimeError(
            "Atomic control-plane op claim is unsupported by the active backend",
        )
    row = mappers.control_plane_op_to_row(record)
    return bool(backend.claim_control_plane_operation_global_row(row))


def finalize_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
    owner_operation_epoch: int | None = None,
) -> bool:
    """Ownership-scoped terminal write of a claimed op (AG3-054 owner-scoped claim).

    Writes the terminal result + clears ``claimed_by`` ONLY when the row is still
    ``claimed`` by ``owner_token``. Returns ``True`` iff this owner's terminal
    write applied; ``False`` when another owner (or an admin-abort) already
    resolved the row in between (the caller must then replay/reject, never
    overwrite).

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW claim instant the owner
    stamped) is given, the CAS also matches ``claimed_at`` so it scopes to THIS
    claim generation -- a stale owner whose token is reused cannot match a NEWER
    claim. ``None`` keeps the legacy owner-only CAS (direct administrative
    callers).

    AG3-138: when ``owner_operation_epoch`` is given, the CAS additionally
    requires the stored ``operation_epoch`` to be unchanged
    (``operation_finalize_requires_cas_on_operation_epoch``).
    """
    backend = _backend_module()
    if not hasattr(backend, "finalize_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op finalize is unsupported by the active backend",
        )
    row = mappers.control_plane_op_to_row(record)
    return bool(
        backend.finalize_control_plane_operation_global_row(
            row,
            owner_token=owner_token,
            owner_claimed_at=owner_claimed_at,
            owner_operation_epoch=owner_operation_epoch,
        )
    )


def claim_inflight_operation_row_global(row: dict[str, Any]) -> bool:
    """Atomically claim an op_id from a caller-built row (AG3-140).

    Returns ``True`` iff this caller inserted the ``claimed`` placeholder (won the
    claim); ``False`` when the op_id already existed (a concurrent/earlier caller
    owns it or it is terminal). Backed by ``INSERT ... ON CONFLICT DO NOTHING``.
    """
    backend = _backend_module()
    if not hasattr(backend, "claim_control_plane_operation_global_row"):
        raise RuntimeError(
            "Atomic control-plane op claim is unsupported by the active backend",
        )
    return bool(backend.claim_control_plane_operation_global_row(row))


def load_inflight_operation_row_global(op_id: str) -> dict[str, Any] | None:
    """Load the raw inflight-operation-record row for ``op_id``, or ``None`` (AG3-140)."""
    backend = _backend_module()
    if not hasattr(backend, "load_control_plane_operation_global_row"):
        raise RuntimeError(
            _GLOBAL_CP_OP_UNSUPPORTED,
        )
    row = backend.load_control_plane_operation_global_row(op_id)
    return dict(row) if row is not None else None


def finalize_inflight_operation_row_global(
    row: dict[str, Any],
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
) -> bool:
    """Ownership-scoped terminal write from a caller-built row (AG3-140).

    Writes the terminal ``status`` + ``response_json`` and clears ``claimed_by``
    ONLY when the row is still ``claimed`` by ``owner_token`` (and, when given,
    the same ``owner_claimed_at`` claim generation). Returns ``True`` iff applied.
    """
    backend = _backend_module()
    if not hasattr(backend, "finalize_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op finalize is unsupported by the active backend",
        )
    return bool(
        backend.finalize_control_plane_operation_global_row(
            row,
            owner_token=owner_token,
            owner_claimed_at=owner_claimed_at,
        )
    )


def finalize_control_plane_start_phase_global(
    record: ControlPlaneOperationRecord,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
    owner_operation_epoch: int | None = None,
    binding: SessionRunBindingRecord | None,
    locks: tuple[StoryExecutionLockRecord, ...],
    events: tuple[ExecutionEventRecord, ...],
    ownership_record_to_insert: RunOwnershipRecord | None = None,
    execution_contract_digest_to_insert: ExecutionContractDigestRecord | None = None,
    expected_ownership_epoch: int | None = None,
) -> bool:
    """Atomically CAS-finalize a start_phase and materialize side effects (#1).

    ERROR-1 fix (#1): the ownership CAS finalize of the claimed ``phase_start`` and
    its canonical side effects (session binding, story/QA locks, lifecycle events)
    are applied in ONE store transaction, gated on still owning the claim. A loser
    (its claim was finalized or admin-aborted by a concurrent process, AG3-138)
    writes NOTHING: the CAS affects zero rows and the whole transaction rolls
    back, so no duplicate / conflicting binding / lock / event is materialized.
    Records are converted to rows HERE (mapper boundary); the driver only sees
    row dicts.

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW claim instant the owner
    stamped) is given, the ownership CAS also matches ``claimed_at`` so it scopes
    to THIS claim generation. ``None`` keeps the legacy owner-only CAS.

    AG3-138: when ``owner_operation_epoch`` is given, the CAS additionally
    requires the stored ``operation_epoch`` to be unchanged
    (``operation_finalize_requires_cas_on_operation_epoch`` -- an
    ``admin_abort_inflight_operation`` bumps the epoch, fencing a late
    executor's finalize even when its owner token/claim instant still matches).

    Args:
        record: The terminal control-plane operation record (committed result).
        owner_token: This caller's owner token (the CAS scope).
        owner_claimed_at: This caller's RAW claim instant (CAS generation scope, #4).
        owner_operation_epoch: This caller's observed fencing epoch (AG3-138).
        binding: The session-run-binding to materialize, or ``None`` (fast story).
        locks: The story/QA lock records to materialize (empty for a fast story).
        events: The lifecycle event records to materialize (empty for fast).
        ownership_record_to_insert: (AG3-142, SOLL-015) The NEW active
            ``RunOwnershipRecord`` (``ownership_epoch=1``, ``acquired_via=setup``)
            to INSERT atomically in this SAME transaction -- a genuinely fresh
            setup start only. ``None`` for every other start/resume finalize.
        execution_contract_digest_to_insert: (AG3-143, FK-44 §44.3a) The run's
            NEW ``ExecutionContractDigestRecord`` to INSERT atomically in this
            SAME transaction -- mirrors ``ownership_record_to_insert`` exactly
            (a genuinely fresh setup start only; ``None`` for every other
            start/resume finalize). Read-only after insert: there is no
            update path.
        expected_ownership_epoch: (AG3-142) When given, re-verify at commit
            time, in this SAME transaction, that the story's active ownership
            record still matches this exact ``(record.run_id,
            record.session_id, expected_ownership_epoch)`` snapshot (no
            TOCTOU). Mutually exclusive in practice with
            ``ownership_record_to_insert`` (a fresh setup has nothing yet to
            fence against).

    Returns:
        ``True`` iff this owner finalized and materialized atomically; ``False``
        when the claim was lost (nothing written).

    Raises:
        OwnershipFenceViolationError: (``expected_ownership_epoch`` given) When
            the active ownership record no longer matches this run/session/epoch
            snapshot at commit time; nothing committed (AG3-142).
    """
    backend = _backend_module()
    if not hasattr(backend, "finalize_control_plane_start_phase_global_row"):
        raise RuntimeError(
            "Control-plane start-phase finalize is unsupported by the active backend",
        )
    return bool(
        backend.finalize_control_plane_start_phase_global_row(
            op_row=mappers.control_plane_op_to_row(record),
            owner_token=owner_token,
            owner_claimed_at=owner_claimed_at,
            owner_operation_epoch=owner_operation_epoch,
            binding_row=(mappers.session_binding_to_row(binding) if binding is not None else None),
            lock_rows=tuple(mappers.execution_lock_to_row(lock) for lock in locks),
            event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
            ownership_row_to_insert=(
                mappers.run_ownership_to_row(ownership_record_to_insert) if ownership_record_to_insert is not None else None
            ),
            execution_contract_digest_row_to_insert=(
                mappers.execution_contract_digest_to_row(execution_contract_digest_to_insert)
                if execution_contract_digest_to_insert is not None
                else None
            ),
            expected_ownership_epoch=expected_ownership_epoch,
        )
    )


def commit_control_plane_operation_with_side_effects_global(
    record: ControlPlaneOperationRecord,
    *,
    binding_to_save: SessionRunBindingRecord | None,
    binding_to_delete: BindingDeleteScope | None,
    locks: tuple[StoryExecutionLockRecord, ...],
    events: tuple[ExecutionEventRecord, ...],
    expected_ownership_epoch: int | None = None,
) -> None:
    """Atomically commit a terminal op AND its side effects (AG3-054 ERROR-2, #2).

    ERROR-2 fix (#2): the conditional op-row upsert (which refuses to clobber a LIVE
    ``claimed`` start claim and raises :class:`ControlPlaneClaimCollisionError`) and
    the mutation's side effects (session-binding create/delete, story/QA lock
    records, lifecycle events) are applied in ONE store transaction, with the
    collision gate running FIRST. A collision rolls back the WHOLE transaction, so a
    complete/fail/closure that hits a live start's op_id leaves NO orphan binding /
    lock / event and the live claimed row intact (the prior code committed the side
    effects in separate transactions BEFORE the collision was detected). Records are
    converted to rows HERE (mapper boundary); the driver only sees row dicts.

    AG3-054 run-scoping sweep: the binding SAVE and DELETE are RUN-scoped at the
    store. ``binding_to_save`` is upserted only when the session is unbound or
    already bound to the SAME ``(project_key, story_id, run_id)``; ``binding_to_delete``
    removes the binding only when it matches the closing run. A binding that belongs
    to a DIFFERENT run (the session was rebound) is left untouched and raises
    :class:`ControlPlaneBindingCollisionError`, rolling back the whole transaction.

    Args:
        record: The terminal control-plane operation record (committed result).
        binding_to_save: A session-run-binding to run-scoped-upsert, or ``None``
            (the complete/fail standard path materializes one; closure never does).
        binding_to_delete: A run-scoped :class:`BindingDeleteScope` whose binding
            must be removed, or ``None`` (closure removes it; complete/fail never).
        locks: The story/QA lock records to upsert (empty when none apply).
        events: The lifecycle event records to append (empty for none).
        expected_ownership_epoch: (AG3-142) When given, re-verify at commit
            time, in this SAME transaction, that the story's active ownership
            record still matches this exact ``(record.run_id,
            record.session_id, expected_ownership_epoch)`` snapshot (no
            TOCTOU) -- used by ``complete_phase`` / ``fail_phase`` / closure.
            ``None`` (the default) skips the fence entirely -- preserved for
            ``story_split``'s reuse of this same primitive (FK-54 §54.8),
            which is fenced by its OWN entry-gate, not run-ownership.

    Raises:
        ControlPlaneClaimCollisionError: When ``record`` collides with a LIVE
            ``claimed`` row (nothing committed; the live claim is intact).
        ControlPlaneBindingCollisionError: When the binding save/delete would touch
            a FOREIGN run's live binding (nothing committed; the binding intact).
        OwnershipFenceViolationError: (``expected_ownership_epoch`` given) When
            the active ownership record no longer matches this run/session/epoch
            snapshot at commit time; nothing committed (AG3-142).
    """
    backend = _backend_module()
    if not hasattr(backend, "commit_control_plane_operation_with_side_effects_global_row"):
        raise RuntimeError(
            "Atomic control-plane mutation commit is unsupported by the active backend",
        )
    backend.commit_control_plane_operation_with_side_effects_global_row(
        op_row=mappers.control_plane_op_to_row(record),
        binding_to_save=(mappers.session_binding_to_row(binding_to_save) if binding_to_save is not None else None),
        binding_to_delete=(
            {
                "session_id": binding_to_delete.session_id,
                "project_key": binding_to_delete.project_key,
                "story_id": binding_to_delete.story_id,
                "run_id": binding_to_delete.run_id,
            }
            if binding_to_delete is not None
            else None
        ),
        expected_ownership_epoch=expected_ownership_epoch,
        lock_rows=tuple(mappers.execution_lock_to_row(lock) for lock in locks),
        event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
    )


def release_control_plane_operation_global(
    op_id: str,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
) -> None:
    """Ownership-scoped release of a claimed control-plane op (AG3-054 owner-scoped claim).

    Deletes the row ONLY when it is still ``claimed`` by ``owner_token``. NEVER an
    unconditional delete: a terminal row or another owner's claim is left intact.
    Idempotent.

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW claim instant the owner
    stamped) is given, the delete CAS also matches ``claimed_at`` so it scopes to
    THIS claim generation -- a stale owner (a reused token in DI/test wiring)
    cannot delete a NEWER claim. ``None`` keeps the legacy owner-only CAS.
    """
    backend = _backend_module()
    if not hasattr(backend, "release_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op release is unsupported by the active backend",
        )
    backend.release_control_plane_operation_global_row(op_id, owner_token=owner_token, owner_claimed_at=owner_claimed_at)


def list_orphaned_claimed_control_plane_operations_global(
    backend_instance_id: str,
    before_incarnation: int,
) -> tuple[ControlPlaneOperationRecord, ...]:
    """List claimed operations orphaned by EARLIER incarnations of THIS instance.

    Startup reconciliation (AG3-138): only claims stamped with the CALLING
    instance's own ``backend_instance_id`` from a strictly earlier
    ``instance_incarnation`` are returned -- never a foreign identity.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_orphaned_claimed_control_plane_operations_global_row(
        backend_instance_id=backend_instance_id,
        before_incarnation=before_incarnation,
    )
    return tuple(mappers.control_plane_op_row_to_record(row) for row in rows)


def finalize_orphaned_control_plane_operation_global(
    *,
    op_id: str,
    backend_instance_id: str,
    status: str,
    response_payload: dict[str, object],
    now: datetime,
    owner_operation_epoch: int,
) -> bool:
    """CAS-finalize one orphaned claim during startup reconciliation (AG3-138).

    Fail-closed identity fence at the store: the CAS additionally matches
    ``backend_instance_id`` -- a claim whose identity is not the caller's own is
    never touched by this call. ``owner_operation_epoch`` (the ``operation_epoch``
    observed by the orphan scan) is MANDATORY and additionally fences the finalize on
    that epoch (AC4), so a row whose epoch moved between scan and finalize -- or a
    malformed ``NULL``-epoch row -- is left untouched
    (``operation_finalize_requires_cas_on_operation_epoch``). There is no identity-only
    (epoch-less) finalize path.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.finalize_orphaned_control_plane_operation_global_row(
            op_id=op_id,
            backend_instance_id=backend_instance_id,
            status=status,
            response_json=mappers.dump_json(response_payload),
            now=now.isoformat(),
            owner_operation_epoch=owner_operation_epoch,
        )
    )


def admin_abort_control_plane_operation_global(
    *,
    op_id: str,
    status: str,
    response_payload: dict[str, object],
    now: datetime,
) -> bool:
    """CAS-abort one in-flight claim via the admin-abort service path (AG3-138).

    Acts on ANY currently-``claimed`` operation (an explicit administrative
    override, FK-91 §91.1a ``admin_abort_inflight_operation``). Returns
    ``False`` when the row is no longer ``claimed`` (already resolved).
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.admin_abort_control_plane_operation_global_row(
            op_id=op_id,
            status=status,
            response_json=mappers.dump_json(response_payload),
            now=now.isoformat(),
        )
    )


def resolve_repair_control_plane_operation_global(
    *,
    op_id: str,
    response_payload: dict[str, object],
    now: datetime,
) -> bool:
    """CAS-resolve one open ``repair`` operation to ``resolved`` (AG3-138, AC10).

    The productive end-way out of the repair mutation lock: transitions a
    ``status = 'repair'`` row to ``resolved`` so the story-scoped lock lifts. Returns
    ``False`` (caller surfaces 409) when the row is not currently in ``repair``.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.resolve_repair_control_plane_operation_global_row(
            op_id=op_id,
            response_json=mappers.dump_json(response_payload),
            now=now.isoformat(),
        )
    )


def has_engine_writes_since_control_plane_claim_global(
    story_id: str,
    since: datetime,
) -> bool:
    """Whether the engine persisted partial writes under a specific claim window.

    Deterministic partial-write detection (AG3-138, IMPL-005): compares ALREADY
    RECORDED timestamps against ``since`` (the claim's own ``claimed_at``) -- never
    the current wall clock. The detection is bound to the concrete operation through
    its claim window (``since``), not a ``run_id`` column: the engine persists an
    engine-internal ``flow_executions.run_id`` distinct from the control-plane
    operation ``run_id``, and ``phase_states`` has no ``run_id`` column, so the claim
    window is the sound operation-binding for both engine tables (see the row-level
    function for the full rationale).
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.has_engine_writes_since_control_plane_claim_global_row(
            story_id=story_id,
            since=since.isoformat(),
        )
    )


def has_open_repair_control_plane_operation_for_story_global(
    project_key: str,
    story_id: str,
) -> bool:
    """Whether *story_id* has an open (unresolved) reconcile/repair state.

    Backs the AC10 fail-closed mutation lock at the dispatch-/operations-layer.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.has_open_repair_control_plane_operation_for_story_global_row(
            project_key=project_key,
            story_id=story_id,
        )
    )


def has_committed_control_plane_operation_for_run_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> bool:
    """Whether a committed control-plane op exists for THIS run (AG3-054 #3).

    Run-scoped admission evidence for complete/fail/closure: a prior COMMITTED
    op whose ``run_id`` matches this exact run.
    """
    backend = _backend_module()
    if not hasattr(backend, "has_committed_control_plane_operation_for_run_global_row"):
        raise RuntimeError(
            "Control-plane run-admission probe is unsupported by the active backend",
        )
    return bool(
        backend.has_committed_control_plane_operation_for_run_global_row(
            project_key,
            story_id,
            run_id,
        )
    )


def has_committed_story_exit_operation_for_run_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> bool:
    """Whether a committed story-exit terminal marker exists for THIS run."""

    backend = _backend_module()
    if not hasattr(backend, "has_committed_story_exit_operation_for_run_global_row"):
        raise RuntimeError("Control-plane story-exit terminal probe is unsupported by the active backend")
    return bool(
        backend.has_committed_story_exit_operation_for_run_global_row(
            project_key,
            story_id,
            run_id,
        )
    )


def delete_control_plane_operation_global(op_id: str) -> None:
    """Unconditional delete of a control-plane op row (administrative recovery).

    Deletes the op row by ``op_id`` regardless of ownership/status. The PRODUCTIVE
    release path is :func:`release_control_plane_operation_global` (ownership-
    scoped). Idempotent: deleting an absent op_id is a no-op.
    """
    backend = _backend_module()
    if not hasattr(backend, "delete_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op deletion is unsupported by the active backend",
        )
    backend.delete_control_plane_operation_global_row(op_id)


def load_control_plane_operation_global(
    op_id: str,
) -> ControlPlaneOperationRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_control_plane_operation_global_row"):
        raise RuntimeError(
            _GLOBAL_CP_OP_UNSUPPORTED,
        )
    row = backend.load_control_plane_operation_global_row(op_id)
    if row is None:
        return None
    return mappers.control_plane_op_row_to_record(row)


__all__ = [
    "save_control_plane_operation_global",
    "claim_control_plane_operation_global",
    "finalize_control_plane_operation_global",
    "claim_inflight_operation_row_global",
    "load_inflight_operation_row_global",
    "finalize_inflight_operation_row_global",
    "finalize_control_plane_start_phase_global",
    "commit_control_plane_operation_with_side_effects_global",
    "release_control_plane_operation_global",
    "list_orphaned_claimed_control_plane_operations_global",
    "finalize_orphaned_control_plane_operation_global",
    "admin_abort_control_plane_operation_global",
    "resolve_repair_control_plane_operation_global",
    "has_engine_writes_since_control_plane_claim_global",
    "has_open_repair_control_plane_operation_for_story_global",
    "has_committed_control_plane_operation_for_run_global",
    "has_committed_story_exit_operation_for_run_global",
    "delete_control_plane_operation_global",
    "load_control_plane_operation_global",
]
