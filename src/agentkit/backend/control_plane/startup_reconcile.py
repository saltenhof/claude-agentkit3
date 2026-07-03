"""Startup reconciliation of orphaned in-flight claims (AG3-138, IMPL-003/IMPL-005).

FK-91 §91.1a rule 16 / FK-10 §10.5.4: "der Server muss über seinen eigenen
Absturz nicht spekulieren; über das Schweigen eines Clients schon". Before the
control-plane listener accepts its first request, THIS instance finalizes every
``claimed`` in-flight operation stamped with its OWN ``backend_instance_id``
from a strictly EARLIER ``instance_incarnation`` (a crash of a previous boot).
Claims of a foreign instance identity are NEVER touched here -- their only
other end-way is the explicit ``admin_abort_inflight_operation`` endpoint
(``formal.state-storage.invariants``
``orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort``).

Deterministic, event-based partial write detection (IMPL-005, no wall-clock
mechanism): an orphaned claim whose ``phase_states``/``flow_executions`` were
already persisted at or after the claim's own ``claimed_at`` goes to an
explicit, auditable ``repair`` state instead of silently ``failed``.

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
    now_fn: Callable[[], datetime] = _default_now,
) -> ReconciliationOutcome:
    """Finalize every orphaned claim of THIS instance's earlier incarnations.

    Args:
        repo: The control-plane runtime repository (orphan-scan, identity-fenced
            finalize and partial-write detection ports).
        identity: THIS boot's resolved backend instance identity (already
            incremented for this boot by :mod:`instance_identity`).
        now_fn: Injectable clock for the ``finalized_at``/``updated_at`` stamp.

    Returns:
        A :class:`ReconciliationOutcome` audit summary.

    Raises:
        StartupReconciliationError: On any failure to complete the scan/finalize
            sequence (fail-closed; the caller must not start serving).
    """
    try:
        return _run(repo, identity, now_fn=now_fn)
    except StartupReconciliationError:
        raise
    except Exception as exc:  # noqa: BLE001 -- fail-closed wrap, never swallowed
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
    now_fn: Callable[[], datetime],
) -> ReconciliationOutcome:
    orphaned = repo.list_orphaned_claimed_operations(
        identity.backend_instance_id,
        identity.instance_incarnation,
    )
    finalized: list[str] = []
    repaired: list[str] = []
    for op in orphaned:
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
