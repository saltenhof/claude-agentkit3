"""Startup reconciliation of orphaned in-flight claims (AG3-138, IMPL-003/IMPL-005).

FK-91 §91.1a rule 16 / FK-10 §10.5.4: a server need not speculate about its own
crash, but it must about a client's silence. Before the control-plane listener
accepts its first request, THIS instance finalizes every ``claimed`` in-flight
operation stamped with its OWN ``backend_instance_id`` from a strictly EARLIER
``instance_incarnation`` (a crash of a previous boot). Claims of a foreign
instance identity are NEVER touched here -- their only other end-way is the
explicit ``admin_abort_inflight_operation`` endpoint
(``formal.state-storage.invariants``
``orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort``).

Deterministic, event-based partial write detection (IMPL-005, no wall-clock
mechanism): an orphaned claim whose ``phase_states``/``flow_executions`` were
already persisted at or after the claim's own ``claimed_at`` goes to an
explicit, auditable ``repair`` state instead of silently ``failed``. This
detection is FAIL-CLOSED-BIASED, not silently permissive: it can only ever route
an orphan toward ``repair`` (a visible, auditable, mutation-locking handling
state), never toward a silent ``failed`` that would drop a real partial write on
the floor. Its residual imprecision -- an occasional over-conservative ``repair``
for a story whose only post-``claimed_at`` engine write actually came from a
different, successfully committed operation -- requires the durable
object-mutation-claim serialization (single active operation per story) to
eliminate, and that serialization is AG3-141's charter (unwired here). See
``has_engine_writes_since_control_plane_claim_global_row`` for the full precision
argument. An over-conservative ``repair`` is never a permanent story deadlock:
it is productively resolvable via the admin-abort repair-resolve path (AC10).

Epoch fence (AC4, IMPL-005): finalize is a mandatory compare-and-swap on the
orphan's ``operation_epoch`` (``operation_finalize_requires_cas_on_operation_epoch``).
An own-identity claim is always AG3-138-stamped and therefore always carries an
``operation_epoch``; a scanned orphan with a ``NULL`` epoch is a contradiction and
is treated fail-closed (the reconciliation aborts, AC9), never finalized without a
fence.

Fail-closed start (AC9): any failure during reconciliation -- a DB error, an
unreachable store -- is surfaced as :class:`StartupReconciliationError` and MUST
propagate uncaught out of the pre-serve hook so the process never starts
serving with an unclear claim inventory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from agentkit.backend.control_plane.models import ControlPlaneMutationResult
from agentkit.backend.control_plane.repository import ObjectMutationClaimRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.records import (
        BackendInstanceIdentityRecord,
        ControlPlaneOperationRecord,
    )
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository

__all__ = (
    "ReconciliationOutcome",
    "StartupReconciliationError",
    "run_startup_reconciliation",
)


class StartupReconciliationError(RuntimeError):
    """Fail-closed signal that startup reconciliation could not complete (AC9).

    The pre-serve startup hook (``control_plane_http.app``) does NOT catch this:
    an unclear claim inventory must never be served, so the process exits
    before ``serve_forever()`` is ever reached.
    """


@dataclass(frozen=True)
class ReconciliationOutcome:
    """Audit summary of one startup-reconciliation run (AG3-138)."""

    #: op_ids of the CALLING instance's own earlier-incarnation orphaned claims
    #: that were deterministically finalized (``failed`` or ``repair``).
    finalized_op_ids: tuple[str, ...]
    #: The subset of ``finalized_op_ids`` that went to the explicit
    #: reconcile/repair state (already-persisted engine writes, IMPL-005).
    repair_op_ids: tuple[str, ...]


def _default_now() -> datetime:
    return datetime.now(UTC)


def run_startup_reconciliation(
    repo: ControlPlaneRuntimeRepository,
    identity: BackendInstanceIdentityRecord,
    *,
    object_claim_repo: ObjectMutationClaimRepository | None = None,
    now_fn: Callable[[], datetime] = _default_now,
) -> ReconciliationOutcome:
    """Finalize every orphaned claim of THIS instance's earlier incarnations.

    Args:
        repo: The control-plane runtime repository (orphan-scan, identity-fenced
            finalize and partial-write detection ports).
        identity: THIS boot's resolved backend instance identity (already
            incremented for this boot by :mod:`instance_identity`).
        object_claim_repo: The object-mutation-claim persistence port (AG3-141
            Scope item 7). ``None`` lazily resolves the productive Postgres-backed
            default; DI-injected in tests (a fake honoring the same release
            contract). Every finalized orphan's declared object-mutation claim is
            released alongside it -- the OTHER explicit non-wall-clock end-way
            besides an ``admin_abort_inflight_operation``
            (``orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort``).
        now_fn: Injectable clock for the ``finalized_at``/``updated_at`` stamp.

    Returns:
        A :class:`ReconciliationOutcome` audit summary.

    Raises:
        StartupReconciliationError: On any failure to complete the scan/finalize
            sequence (fail-closed; the caller must not start serving).
    """
    try:
        return _run(repo, identity, object_claim_repo=object_claim_repo, now_fn=now_fn)
    except StartupReconciliationError:
        raise
    # Fail-closed wrap: the broad catch is intentional and never swallows -- every
    # non-specific failure is re-raised as StartupReconciliationError so the
    # pre-serve hook aborts the boot (AC9).
    except Exception as exc:  # noqa: BLE001
        raise StartupReconciliationError(
            "startup reconciliation failed: the claim inventory of instance "
            f"{identity.backend_instance_id!r} (incarnation "
            f"{identity.instance_incarnation}) could not be established; "
            f"refusing to start serving requests (fail-closed, AC9). Cause: {exc}",
        ) from exc


def _run(
    repo: ControlPlaneRuntimeRepository,
    identity: BackendInstanceIdentityRecord,
    *,
    object_claim_repo: ObjectMutationClaimRepository | None,
    now_fn: Callable[[], datetime],
) -> ReconciliationOutcome:
    claim_repo = object_claim_repo or ObjectMutationClaimRepository()
    orphaned = repo.list_orphaned_claimed_operations(
        identity.backend_instance_id,
        identity.instance_incarnation,
    )
    finalized: list[str] = []
    repaired: list[str] = []
    for op in orphaned:
        if op.operation_epoch is None:
            #: Fail-closed (AC4/AC9): a scanned own-identity orphan ALWAYS carries an
            #: ``operation_epoch`` (AG3-138 stamps it on every claim; the orphan scan
            #: only returns rows whose ``backend_instance_id`` matched this instance,
            #: so a pre-AG3-137 legacy row with a NULL instance is never scanned here).
            #: A NULL epoch on a scanned orphan is therefore a contradiction; we refuse
            #: to finalize it without the mandatory epoch fence rather than fall back to
            #: an identity-only finalize (which would violate
            #: ``operation_finalize_requires_cas_on_operation_epoch``).
            raise StartupReconciliationError(
                f"orphaned claim {op.op_id!r} of backend instance "
                f"{identity.backend_instance_id!r} carries no operation_epoch; "
                "refusing an unfenced finalize (fail-closed, AC4/AC9).",
            )
        status, note = _resolve_terminal_status(repo, op, identity=identity)
        response_payload = _orphan_result_payload(op, status=status, admin_note=note)
        applied = repo.finalize_orphaned_operation(
            op_id=op.op_id,
            backend_instance_id=identity.backend_instance_id,
            status=status,
            response_payload=response_payload,
            now=now_fn(),
            owner_operation_epoch=op.operation_epoch,
        )
        if not applied:
            # The row changed underneath the scan (e.g. concurrently resolved by
            # an admin-abort). Idempotent-safe: not this call's finalize to make.
            continue
        finalized.append(op.op_id)
        if status == "repair":
            repaired.append(op.op_id)
    #: AG3-141 Scope item 7 (SOLL-066 object-claims part): DIRECTLY scan the
    #: ``object_mutation_claims`` table for every claim orphaned by THIS
    #: instance's earlier incarnations and release it. A direct scan of the
    #: claim table (not a cascade off the finalized in-flight operations above)
    #: is REQUIRED for completeness: a crashed complete/fail/closure mutation
    #: holds a durable object claim yet leaves NO ``claimed`` control-plane
    #: operation row (it commits in a single transaction, or crashes before it
    #: does), so an operation-keyed cascade would never reach it and its object
    #: claim would block the story forever. The scan is the OTHER explicit
    #: non-wall-clock end-way besides ``admin_abort_inflight_operation``
    #: (``orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort``);
    #: only claims stamped with THIS ``backend_instance_id`` from a strictly
    #: earlier ``instance_incarnation`` are released -- never a foreign
    #: identity, never a wall-clock/TTL expiry. Ownership-scoped release
    #: (op_id-CAS) is idempotent, so a re-run or a concurrently freed claim is
    #: a safe no-op.
    for claim in claim_repo.list_orphaned(
        identity.backend_instance_id, identity.instance_incarnation
    ):
        claim_repo.release_claim(
            claim.project_key,
            claim.serialization_scope,
            claim.scope_key,
            claim.op_id,
        )
    return ReconciliationOutcome(
        finalized_op_ids=tuple(finalized),
        repair_op_ids=tuple(repaired),
    )


def _resolve_terminal_status(
    repo: ControlPlaneRuntimeRepository,
    op: ControlPlaneOperationRecord,
    *,
    identity: BackendInstanceIdentityRecord,
) -> tuple[Literal["failed", "repair"], str]:
    """Decide ``failed`` vs ``repair`` for one orphaned claim (IMPL-005)."""
    since = op.claimed_at or op.created_at
    has_writes = repo.has_engine_writes_since(op.story_id, since)
    if has_writes:
        return (
            "repair",
            "startup reconciliation: orphaned claim from an earlier incarnation "
            f"({op.instance_incarnation}) of backend instance "
            f"{identity.backend_instance_id!r} (now at incarnation "
            f"{identity.instance_incarnation}) already persisted engine writes "
            "(phase_states/flow_executions) before the crash; entering an "
            "explicit, auditable reconcile/repair state instead of silently "
            "'failed' (IMPL-005).",
        )
    return (
        "failed",
        "startup reconciliation: orphaned claim from an earlier incarnation "
        f"({op.instance_incarnation}) of backend instance "
        f"{identity.backend_instance_id!r} (now at incarnation "
        f"{identity.instance_incarnation}) with no persisted engine writes; "
        "deterministically finalized as failed (FK-91 §91.1a rule 16).",
    )


def _orphan_result_payload(
    op: ControlPlaneOperationRecord,
    *,
    status: Literal["failed", "repair"],
    admin_note: str,
) -> dict[str, object]:
    """Build the terminal :class:`ControlPlaneMutationResult` payload for *op*."""
    result = ControlPlaneMutationResult(
        status=status,
        op_id=op.op_id,
        operation_kind=op.operation_kind,
        run_id=op.run_id,
        phase=op.phase,
        edge_bundle=None,
        phase_dispatch=None,
        admin_note=admin_note,
    )
    return result.model_dump(mode="json")
