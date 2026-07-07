"""Administrative operation transition handling."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from agentkit.backend.control_plane import (
    object_claims,
)
from agentkit.backend.control_plane.models import (
    AdminAbortRequest,
    ControlPlaneMutationResult,
)

# Deliberate RUNTIME re-import (not TYPE_CHECKING): this is the SSOT re-import of
# the canonical FK-56 operating-mode literal from its SINGLE foundation definition
# (``core_types.operating_mode``). It must be a runtime binding so the
# single-definition identity holds for consumers (and is assertable) -- moving it
# into a type-checking block would make ``control_plane.runtime.OperatingMode`` a
# different/absent object at runtime, defeating the AK2 SSOT consolidation.
from ._models import OperationNotAbortableError, OperationNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane.records import (
        ControlPlaneOperationRecord,
    )
    from agentkit.backend.control_plane.repository import (
        ControlPlaneRuntimeRepository,
        ObjectMutationClaimRepository,
    )

logger = logging.getLogger(__name__)

class _AdminTransitionMixin:
    """AG3-138 ``admin_transition`` abort + repair-resolve service methods (mixin).

    Cohesive admin-abort / partial-write-repair / repair-resolve logic, split out of
    :class:`ControlPlaneRuntimeService` for cohesion (no behaviour change). The
    concrete runtime supplies the shared dependencies below.
    """

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository
        _now_fn: Callable[[], datetime]
        _object_claim_repo: ObjectMutationClaimRepository

        def _require_postgres_backend_on_first_use(self) -> None: ...
        def _release_claim_key_best_effort(self, key: object_claims.ObjectClaimKey, *, op_id: str) -> None: ...

    def admin_abort_inflight_operation(
        self,
        op_id: str,
        request: AdminAbortRequest,
    ) -> ControlPlaneMutationResult:
        """Administratively abort a hanging server-owned in-flight operation (AG3-138).

        FK-91 §91.1a ``admin_abort_inflight_operation`` (FK-55 §55.5
        ``admin_transition``): the explicit manual end-way for an in-flight claim
        beside the same-instance startup reconciliation, AND the productive exit from
        the ``repair`` mutation lock (NO ERROR BYPASSING -- no back door that just
        "frees" claims or "clears" the lock). Acts on the two admin-actionable
        (non-closed) states:

        * a currently-``claimed`` operation (a server-owned in-flight claim) is
          CAS-aborted: it bumps ``operation_epoch`` so a late, physically-still-
          running executor's finalize fails the epoch fence deterministically -- at
          most a no-op abort note, never a second result or a silent state change
          (AC4/AC6; ``operation_finalize_requires_cas_on_operation_epoch``) -- and
          routes a partial write (already-persisted ``phase_states``/
          ``flow_executions``) into the explicit, auditable ``repair`` state instead
          of silently ``failed`` (IMPL-005), which then story-scoped mutation-locks
          the run (AC10);
        * an open ``repair`` operation is CAS-resolved to ``resolved``, lifting the
          story-scoped mutation lock so mutating operations are re-admitted (AC10).
          This is the productive end-way out of ``repair``, so even an
          over-conservative repair (see the partial-write detector) can never be a
          permanent story deadlock.

        Both transitions are fully audited: the actor (``session_id`` /
        ``principal_type``) and the mandatory ``reason`` are persisted on the terminal
        operation record (visible via ``GET operations/{op_id}``).

        Args:
            op_id: The target operation id (URL path segment).
            request: The audited admin-abort request (actor + reason).

        Returns:
            The terminal :class:`ControlPlaneMutationResult`: for a ``claimed``
            target ``aborted`` (no partial writes) or ``repair`` (partial writes
            detected); for a ``repair`` target ``resolved``. An unknown op is 404; a
            target in a truly closed terminal status (or resolved concurrently) is a
            fail-closed 409.

        Raises:
            OperationNotFoundError: When ``op_id`` does not exist (HTTP 404).
            OperationNotAbortableError: When the operation is neither ``claimed`` nor
                ``repair`` (already closed terminal, HTTP 409), or was resolved
                concurrently between the load and the CAS.
        """
        self._require_postgres_backend_on_first_use()
        record = self._repo.load_operation(op_id)
        if record is None:
            raise OperationNotFoundError(op_id)
        if record.status == "claimed":
            return self._abort_claimed_operation(record, request)
        if record.status == "repair":
            #: AC10 productive end-way: admin-abort of an OPEN ``repair`` state closes
            #: it out to ``resolved``, lifting the story-scoped mutation lock. This is
            #: the one manual exit from ``repair`` (NO ERROR BYPASSING -- no back door
            #: that just clears the lock); ``repair`` is not a closed terminal but an
            #: open, admin-actionable handling state.
            return self._resolve_repair_operation(record, request)
        #: Any truly closed terminal status (committed/aborted/failed/resolved/...) is
        #: not abortable (AC6, 409).
        raise OperationNotAbortableError(op_id, record.status)

    def _abort_claimed_operation(
        self,
        record: ControlPlaneOperationRecord,
        request: AdminAbortRequest,
    ) -> ControlPlaneMutationResult:
        """CAS-abort a currently-``claimed`` operation (AC6, partial write -> repair)."""
        status, admin_note = self._resolve_abort_terminal_status(record, request)
        result = ControlPlaneMutationResult(
            status=status,
            op_id=record.op_id,
            operation_kind=record.operation_kind,
            run_id=record.run_id,
            phase=record.phase,
            edge_bundle=None,
            phase_dispatch=None,
            admin_note=admin_note,
        )
        applied = self._repo.admin_abort_operation(
            op_id=record.op_id,
            status=status,
            response_payload=result.model_dump(mode="json"),
            now=self._now_fn(),
        )
        if not applied:
            #: The claim was concurrently resolved (finalized/aborted) between the
            #: load and the CAS. Fail-closed: it is no longer an abortable
            #: in-flight claim (AC6, 409). NO second/duplicate terminal write.
            raise OperationNotAbortableError(record.op_id, "resolved_concurrently")
        #: Scope item 7 (SOLL-066 object-claims part): admin_abort releases the
        #: aborted operation's object-mutation claim -- the OTHER explicit
        #: non-wall-clock end-way besides the AG3-138 startup reconciliation
        #: (``orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort``).
        #: Best-effort: a legacy/pre-AG3-141 row with no declared scope has
        #: nothing to release (``parse_declared_scope`` returns ``None``).
        claim_key = object_claims.parse_declared_scope(record.project_key, record.declared_serialization_scope)
        if claim_key is not None:
            self._release_claim_key_best_effort(claim_key, op_id=record.op_id)
        return result

    def _resolve_repair_operation(
        self,
        record: ControlPlaneOperationRecord,
        request: AdminAbortRequest,
    ) -> ControlPlaneMutationResult:
        """CAS-resolve an open ``repair`` operation to ``resolved`` (AC10 lock exit)."""
        actor = f"session={request.session_id!r} principal={request.principal_type!r}"
        admin_note = (
            f"repair resolved by {actor}: reason={request.reason!r}. The open "
            "reconcile/repair state was administratively closed out to 'resolved'; "
            "the story-scoped mutation lock is lifted and mutating operations are "
            "re-admitted (AC10). op-class admin_transition (FK-55 §55.5)."
        )
        result = ControlPlaneMutationResult(
            status="resolved",
            op_id=record.op_id,
            operation_kind=record.operation_kind,
            run_id=record.run_id,
            phase=record.phase,
            edge_bundle=None,
            phase_dispatch=None,
            admin_note=admin_note,
        )
        applied = self._repo.resolve_repair_operation(
            op_id=record.op_id,
            response_payload=result.model_dump(mode="json"),
            now=self._now_fn(),
        )
        if not applied:
            #: The repair row moved off ``repair`` (resolved concurrently) between the
            #: load and the CAS. Fail-closed: no second/duplicate resolve (AC6, 409).
            raise OperationNotAbortableError(record.op_id, "resolved_concurrently")
        return result

    def _resolve_abort_terminal_status(
        self,
        record: ControlPlaneOperationRecord,
        request: AdminAbortRequest,
    ) -> tuple[Literal["aborted", "repair"], str]:
        """Decide ``aborted`` vs ``repair`` for an admin-abort target (IMPL-005)."""
        since = record.claimed_at or record.created_at
        has_writes = self._repo.has_engine_writes_since(record.story_id, since)
        actor = f"session={request.session_id!r} principal={request.principal_type!r}"
        if has_writes:
            return (
                "repair",
                f"admin_abort_inflight_operation by {actor}: reason="
                f"{request.reason!r}. The aborted operation had already persisted "
                "engine writes (phase_states/flow_executions); entering an "
                "explicit, auditable reconcile/repair state instead of silently "
                "'failed' (IMPL-005). The story is mutation-locked until the state "
                "is resolved via repair (AC10).",
            )
        return (
            "aborted",
            f"admin_abort_inflight_operation by {actor}: reason={request.reason!r}. "
            "No persisted engine writes detected; the in-flight claim is aborted "
            "and its operation_epoch bumped so a late executor's finalize fails "
            "the fence deterministically (AC4).",
        )
