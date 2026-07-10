"""Control-plane runtime closure completion responsibilities."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.control_plane import (
    runtime_constants,
)
from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
)
from agentkit.backend.control_plane.records import (
    BindingDeleteScope,
    SessionRunBindingRecord,
)
from agentkit.backend.exceptions import (
    ControlPlaneBindingCollisionError,
    ControlPlaneClaimCollisionError,
    OwnershipFenceViolationError,
)
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.telemetry.events import EventType

from ._closure import _complete_fast_closure
from ._edge_bundles import _build_edge_bundle, _next_binding_version
from ._models import (
    _claimed_operation_rejection_reason,
    _closure_binding_collision_reason,
)
from ._operation_records import (
    _control_plane_request_body_hash,
    _lifecycle_event_record,
    _object_claim_busy_rejection,
    _operation_record,
    _rejection_result,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane import object_claims
    from agentkit.backend.control_plane.models import PhaseMutationRequest
    from agentkit.backend.control_plane.ownership_fence import OwnershipAdmission
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository

    from ._models import MergePrecondition, _ModeResolutionKeys

logger = logging.getLogger(__name__)


class _ControlPlaneClosureMixin:
    """Complete closure and tear down run-scoped guard regimes."""

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository

        def _require_postgres_backend_on_first_use(self) -> None: ...

        def _load_existing_operation(
            self,
            request: PhaseMutationRequest | ClosureCompleteRequest,
            *,
            operation_kind: str,
            phase: str | None,
            mutating_retry: bool = True,
        ) -> ControlPlaneMutationResult | None: ...

        def _repair_locked_rejection(
            self,
            *,
            project_key: str,
            story_id: str,
            operation_kind: str,
            op_id: str,
            run_id: str | None,
            phase: str,
        ) -> ControlPlaneMutationResult | None: ...

        def _closure_run_was_admitted(self, request: ClosureCompleteRequest, *, run_id: str) -> OwnershipAdmission: ...

        def _unadmitted_run_rejection(
            self,
            admission: OwnershipAdmission,
            *,
            op_id: str,
            operation_kind: str,
            run_id: str | None,
            phase: str | None,
            reason: str,
            session_id: str,
        ) -> ControlPlaneMutationResult: ...

        def _closure_push_precondition_block(
            self, *, project_key: str, story_id: str, run_id: str, sync_point_id: str
        ) -> MergePrecondition | None: ...

        def _acquire_object_claim(
            self, *, project_key: str, story_id: str, op_id: str
        ) -> object_claims.ObjectClaimConflict | None: ...

        def _release_object_claim(self, *, project_key: str, story_id: str, op_id: str) -> None: ...

        def _release_object_claim_best_effort(self, *, project_key: str, story_id: str, op_id: str) -> None: ...

        def _story_lock_records_apply(self, request: _ModeResolutionKeys) -> bool: ...

        def _ownership_fence_violation_rejection(
            self,
            exc: OwnershipFenceViolationError,
            *,
            op_id: str,
            operation_kind: str,
            run_id: str | None,
            phase: str | None,
        ) -> ControlPlaneMutationResult: ...

    def complete_closure(
        self,
        *,
        run_id: str,
        request: ClosureCompleteRequest,
    ) -> ControlPlaneMutationResult:
        """Complete closure for a story run, tearing down its guard regime.

        AG3-018 FIX-2 (FK-24 §24.3.4; ``no_locks_active``): the authoritative
        story mode is resolved server-side (same sanctioned surface as
        ``_mutate_phase``; fail-closed-to-standard on an unresolvable
        ``StoryContext``). A FAST story never activated story-scoped guards, so
        its closure is a true no-op -- it creates NO ``story_execution`` /
        ``qa_artifact_write`` lock-records and emits NO story-execution
        deactivation events (see :meth:`_complete_fast_closure`). Standard /
        exploration closure is unchanged: it writes the INACTIVE lock-records and
        emits the binding-removed + regime-deactivated events.

        Args:
            run_id: The story run identifier.
            request: The closure completion request.

        Returns:
            The committed (or replayed) closure :class:`ControlPlaneMutationResult`.
        """
        self._require_postgres_backend_on_first_use()
        existing = self._load_existing_operation(request, operation_kind="closure_complete", phase="closure")
        if existing is not None:
            return existing
        locked = self._repair_locked_rejection(
            project_key=request.project_key,
            story_id=request.story_id,
            operation_kind="closure_complete",
            op_id=request.op_id,
            run_id=run_id,
            phase="closure",
        )
        if locked is not None:
            return locked

        closure_admission = self._closure_run_was_admitted(request, run_id=run_id)
        if not closure_admission.admitted:
            #: ERROR-6 fix (#6): closure is consistent with complete/fail admission
            #: -- a closure for a run with NO active ownership record must NOT
            #: commit. Fail-closed: an unadmitted closure never tears down (or
            #: fabricates) a guard regime. The AG3-018 fast-story no-op is
            #: PRESERVED when there WAS a prior admitted run (the fast story's
            #: admitted setup left an active record), so a legitimate fast
            #: closure still no-ops below.
            return self._unadmitted_run_rejection(
                closure_admission,
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                session_id=request.session_id,
                reason=(
                    "closure_complete rejected: the run has no active "
                    "run-ownership record for THIS project/story/run; "
                    "fail-closed -- closure must not commit for an unadmitted "
                    "run (FK-56 §56.8a)."
                ),
            )

        #: AG3-147 (FK-10 §10.2.4b boundary type 4 + FK-12 §12.4.3, SOLL-190):
        #: the closure-entry push barrier. Closure entry is fail-closed BLOCKED
        #: unless the story branch is server-verified-pushed in EVERY participating
        #: repo -- via the persisted closure-entry barrier SSOT. Checked AFTER
        #: admission, BEFORE the object claim + teardown, so a blocked barrier
        #: tears down NOTHING.
        merge_block = self._closure_push_precondition_block(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            sync_point_id=run_id,
        )
        if merge_block is not None:
            return _rejection_result(
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                reason=(
                    f"{runtime_constants.PUSH_BARRIER_BLOCKED_CODE}: "
                    "closure_complete blocked -- the "
                    "story branch is not server-verified-pushed in every "
                    f"participating repo (FK-12 §12.4.3 / SOLL-190, fail-closed). "
                    f"{merge_block.detail}"
                ),
                dispatch_phase="closure",
            )

        #: SOLL-054: closure competes for the SAME per-story object claim as
        #: start/resume/complete/fail (FK-91 §91.1a Rule 13). A busy object
        #: returns the K4 deterministic 409 + Retry-After (IMPL-016); NO
        #: operation is stored for this attempt.
        object_conflict = self._acquire_object_claim(
            project_key=request.project_key,
            story_id=request.story_id,
            op_id=request.op_id,
        )
        if object_conflict is not None:
            return _object_claim_busy_rejection(
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                conflict=object_conflict,
            )
        now = datetime.now(tz=UTC)
        #: ``closure_admission.admitted`` is True, so ``active_record`` is
        #: present (``evaluate_ownership_admission``).
        assert closure_admission.active_record is not None  # noqa: S101
        expected_ownership_epoch = closure_admission.active_record.ownership_epoch
        committed = False
        try:
            if not self._story_lock_records_apply(request):
                result = _complete_fast_closure(
                    self._repo,
                    run_id=run_id,
                    request=request,
                    now=now,
                    expected_ownership_epoch=expected_ownership_epoch,
                )
            else:
                result = self._complete_standard_closure(
                    run_id=run_id,
                    request=request,
                    now=now,
                    expected_ownership_epoch=expected_ownership_epoch,
                )
            committed = True
            #: Codex-R1 (BLOCKER) fix: NON-best-effort release on the committed
            #: path -- a release failure SURFACES (raises -> 5xx), never swallowed
            #: while the API returns ``committed`` with a durably-held claim (closure
            #: leaves NO ``claimed`` op row, so admin_abort cannot target a swallowed
            #: stuck claim -- only a same-instance restart reconciliation frees it).
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return result
        except OwnershipFenceViolationError as exc:
            #: AG3-142 (no TOCTOU): the ownership fence re-check at commit time
            #: failed -- a takeover landed between the early admission check
            #: above and this commit. The transaction rolled back (no side
            #: effect, no stored op, claim still held): release NON-best-effort
            #: before surfacing the rich ex-owner rejection.
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return self._ownership_fence_violation_rejection(
                exc,
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
            )
        except ControlPlaneClaimCollisionError:
            #: ERROR-3 fix (#3): the op_id is held by a LIVE ``claimed`` start
            #: claim; the store refused to clobber it. A closure reusing a live
            #: start's op_id is rejected fail-closed (consistent with
            #: complete/fail), never stealing the start's ownership. The commit
            #: transaction rolled back (no op committed, claim still held): release
            #: NON-best-effort (surface failures) before the fail-closed rejection.
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            reason = _claimed_operation_rejection_reason("closure_complete", request.op_id, "closure")
            return _rejection_result(
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                reason=reason,
                dispatch_phase="closure",
            )
        except ControlPlaneBindingCollisionError as exc:
            #: AG3-054 run-scoping sweep: the session is bound to a DIFFERENT run
            #: (it was rebound after this old run's setup). The tombstone derivation
            #: and/or the run-scoped binding DELETE refused fail-closed and the WHOLE
            #: teardown rolled back -- the foreign run's binding is intact, NO
            #: INACTIVE locks were written and NO deactivation events were emitted. A
            #: stale closure for an old run must never tear down a foreign run's live
            #: regime. The commit rolled back (claim still held): release
            #: NON-best-effort (surface failures) before the fail-closed rejection.
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            reason = _closure_binding_collision_reason(exc)
            return _rejection_result(
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                reason=reason,
                dispatch_phase="closure",
            )
        except BaseException:
            #: A pre-commit error (or a real process crash) BEFORE the op committed:
            #: best-effort release so the ORIGINAL error is never masked; a true
            #: crash leaves the claim held for reconcile/admin_abort only (AC1).
            if not committed:
                self._release_object_claim_best_effort(
                    project_key=request.project_key,
                    story_id=request.story_id,
                    op_id=request.op_id,
                )
            raise

    def _complete_standard_closure(
        self,
        *,
        run_id: str,
        request: ClosureCompleteRequest,
        now: datetime,
        expected_ownership_epoch: int,
    ) -> ControlPlaneMutationResult:
        """Tear down a standard/exploration run's guard regime at closure.

        Writes the INACTIVE story/QA lock-records, removes the session binding and
        emits the binding-removed + regime-deactivated lifecycle events, then
        commits the idempotent closure operation -- ALL in ONE atomic transaction
        (ERROR-2, #2). The op-row write is the ERROR-3 conditional upsert with the
        collision gate running FIRST, so a closure that reuses a LIVE ``claimed``
        start's op_id raises :class:`ControlPlaneClaimCollisionError` (handled
        fail-closed by :meth:`complete_closure`) and the WHOLE transaction rolls
        back -- the binding is NOT deleted, the locks are NOT deactivated and no
        event is emitted (the prior code committed those side effects BEFORE the
        collision was detected -> orphan teardown).

        AG3-054 run-scoping sweep: the tombstone-root derivation uses the CLOSING
        run's binding, never "whatever binding exists". If the live binding for the
        session belongs to a DIFFERENT run (the session was rebound), this fails
        closed (:class:`ControlPlaneBindingCollisionError`) BEFORE any teardown is
        planned -- a stale closure for an old run must not derive its tombstone from,
        or tear down, a foreign run's live regime. The atomic binding DELETE is also
        run-scoped at the store, so even a TOCTOU rebind between this read and the
        commit is caught and rolls back the whole transaction.
        """
        binding = self._run_matched_binding_for_teardown(request, run_id=run_id)
        worktree_roots = binding.worktree_roots if binding is not None else ()
        binding_version = binding.binding_version if binding is not None else _next_binding_version(None)
        lock = StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            lock_type="story_execution",
            status="INACTIVE",
            worktree_roots=tuple(worktree_roots),
            binding_version=binding_version,
            activated_at=now,
            updated_at=now,
            deactivated_at=now,
        )
        qa_lock = StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            lock_type="qa_artifact_write",
            status="INACTIVE",
            worktree_roots=tuple(worktree_roots),
            binding_version=binding_version,
            activated_at=now,
            updated_at=now,
            deactivated_at=now,
        )
        bundle = _build_edge_bundle(
            binding=None,
            lock=lock,
            qa_lock=qa_lock,
            sync_class="mutation",
            now=now,
            tombstone_worktree_roots=tuple(worktree_roots),
        )
        events = (
            _lifecycle_event_record(
                event_type=EventType.SESSION_RUN_BINDING_REMOVED,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
                source_component=request.source_component,
                payload={
                    "session_id": request.session_id,
                    "ownership_epoch": expected_ownership_epoch,
                },
                now=now,
            ),
            _lifecycle_event_record(
                event_type=EventType.STORY_EXECUTION_REGIME_DEACTIVATED,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
                source_component=request.source_component,
                payload={
                    "session_id": request.session_id,
                    "ownership_epoch": expected_ownership_epoch,
                },
                now=now,
            ),
        )
        result = ControlPlaneMutationResult(
            status="committed",
            op_id=request.op_id,
            operation_kind="closure_complete",
            run_id=run_id,
            phase="closure",
            edge_bundle=bundle,
            ownership_epoch=expected_ownership_epoch,
        )
        record = _operation_record(
            op_id=request.op_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            session_id=request.session_id,
            operation_kind="closure_complete",
            phase="closure",
            result=result,
            now=now,
            request_body_hash=_control_plane_request_body_hash(request, operation_kind="closure_complete", phase="closure"),
        )
        #: Atomic: the conditional op-row upsert (collision gate FIRST) + the
        #: INACTIVE locks, the binding deletion and the deactivation events apply in
        #: ONE transaction. A live-claim collision rolls back EVERYTHING (no orphan
        #: teardown), surfaced fail-closed by :meth:`complete_closure`.
        self._repo.commit_operation_with_side_effects(
            record,
            binding_to_save=None,
            binding_to_delete=BindingDeleteScope(
                session_id=request.session_id,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
            ),
            locks=(lock, qa_lock),
            events=events,
            expected_ownership_epoch=expected_ownership_epoch,
        )
        return result

    def _run_matched_binding_for_teardown(
        self,
        request: ClosureCompleteRequest,
        *,
        run_id: str,
    ) -> SessionRunBindingRecord | None:
        """Resolve the CLOSING run's binding for teardown, else fail closed (#2).

        AG3-054 run-scoping sweep: tombstone-root / binding-version derivation at
        closure must read the binding that belongs to THIS run, never "whatever
        binding exists" for the session. Returns:

        * the binding when it EXACTLY matches ``(project_key, story_id, run_id)``;
        * ``None`` when no binding exists for the session (a fast / already-cleaned
          run -- a benign no-op teardown).

        Fail-closed: a binding that exists but belongs to a DIFFERENT run (the
        session was rebound to a NEW run) raises
        :class:`ControlPlaneBindingCollisionError` so a stale closure for the old run
        neither derives its tombstone from, nor tears down, the foreign run's live
        regime.

        Raises:
            ControlPlaneBindingCollisionError: When a live binding exists for the
                session but belongs to a DIFFERENT run.
        """
        binding = self._repo.load_binding(request.session_id)
        if binding is None:
            return None
        if binding.project_key == request.project_key and binding.story_id == request.story_id and binding.run_id == run_id:
            return binding
        raise ControlPlaneBindingCollisionError(
            f"closure for run {run_id!r} refused: session "
            f"{request.session_id!r} is bound to run {binding.run_id!r} "
            f"(project={binding.project_key!r}, story={binding.story_id!r}); a "
            "stale closure must not tear down a foreign run's live binding "
            "(AG3-054 run-scoping, fail-closed).",
        )


__all__ = ["_ControlPlaneClosureMixin"]
