"""ProjectEdge command handling and push-freshness operations."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast

from agentkit.backend.control_plane import (
    object_claims,
    push_barrier_lifecycle,
    runtime_constants,
)
from agentkit.backend.control_plane.models import (
    EdgeCommandMutationResult,
    EdgeCommandResultPayload,
    EdgeCommandResultRequest,
    EdgeCommandView,
    OpenEdgeCommandsResponse,
    OwnershipTransferredDetail,
    PushFreshnessListResponse,
    PushFreshnessView,
    PushOwnershipConfirmation,
)
from agentkit.backend.control_plane.ownership_fence import (
    ERROR_CODE_OWNERSHIP_TRANSFERRED,
    ERROR_CODE_STORY_FROZEN,
    OwnershipAdmission,
    OwnershipRejectionReason,
)
from agentkit.backend.control_plane.push_sync import (
    PushBarrierVerdict,
    PushBarrierVerdictStatus,
    RepoPushVerificationInput,
    SyncPointBarrierType,
    authorize_story_ref_write,
    evaluate_repo_push,
    project_push_freshness,
)
from agentkit.backend.control_plane.records import (
    ControlPlaneOperationRecord,
    EdgeCommandRecord,
)
from agentkit.backend.exceptions import (
    ControlPlaneClaimCollisionError,
    EdgeCommandNotOpenError,
    OwnershipFenceViolationError,
)

from ._push_barrier_results import (
    _push_barrier_result_binding,
    _push_barrier_result_is_fenced,
    _sync_point_id_from_sync_push_command,
    _sync_push_failed_barrier_verdict,
    _sync_push_result_repo_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.repository import (
        ControlPlaneRuntimeRepository,
        EdgeCommandRepository,
    )

logger = logging.getLogger(__name__)

class _EdgeCommandMixin:
    """Edge-Command-Queue GET/POST service methods (FK-91 §91.1b, AG3-145 mixin).

    Cohesive command-list-and-ack + command-result-commit logic, split out of
    :class:`ControlPlaneRuntimeService` for cohesion (PY_CLASS_MAX_LOC_800; no
    behaviour change). The concrete runtime supplies the shared dependencies
    below.
    """

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository
        _edge_command_repo: EdgeCommandRepository
        _now_fn: Callable[[], datetime]

        def _require_postgres_backend_on_first_use(self) -> None: ...
        def _evaluate_run_admission(
            self,
            *,
            project_key: str,
            story_id: str,
            session_id: str,
            run_id: str,
            command_id: str,
        ) -> OwnershipAdmission: ...
        def _acquire_object_claim(
            self, *, project_key: str, story_id: str, op_id: str
        ) -> object_claims.ObjectClaimConflict | None: ...
        def _release_object_claim(self, *, project_key: str, story_id: str, op_id: str) -> None: ...
        def _release_object_claim_best_effort(self, *, project_key: str, story_id: str, op_id: str) -> None: ...
        def _load_boundary_verdict(
            self,
            *,
            project_key: str,
            story_id: str,
            run_id: str,
            boundary_type: SyncPointBarrierType,
            boundary_id: str,
            repo_id: str,
        ) -> PushBarrierVerdict | None: ...
        def _upsert_boundary_verdict(self, verdict: PushBarrierVerdict) -> None: ...
        def _collect_push_barrier_inputs(
            self,
            *,
            project_key: str,
            story_id: str,
            run_id: str,
            required_sync_point_id: str | None = None,
        ) -> tuple[RepoPushVerificationInput, ...] | None: ...

    def list_and_ack_open_commands(
        self,
        run_id: str,
        *,
        project_key: str,
        session_id: str,
    ) -> OpenEdgeCommandsResponse:
        """``GET .../story-runs/{run_id}/commands`` (FK-91 §91.1b, AG3-145 AC1).

        Read-only Ack (Rule 13: "reads never take locks") -- the fetch
        stamps delivery (``created`` -> ``delivered``) but acquires no
        lock/claim. Scoped to ``(project_key, run_id, session_id)`` at the
        store: a foreign session's query matches zero rows -- fail-closed by
        construction, never a session-identity check that could be bypassed.
        """
        self._require_postgres_backend_on_first_use()
        records = self._edge_command_repo.list_and_ack_open_commands(
            project_key=project_key,
            run_id=run_id,
            session_id=session_id,
            delivered_at=self._now_fn(),
        )
        return OpenEdgeCommandsResponse(
            commands=[
                EdgeCommandView(
                    command_id=record.command_id,
                    command_kind=record.command_kind,
                    payload=record.payload,
                    status=cast("Literal['created', 'delivered']", record.status),
                    created_at=record.created_at,
                )
                for record in records
            ]
        )

    def list_push_freshness(
        self,
        run_id: str,
        *,
        project_key: str,
        story_id: str,
    ) -> PushFreshnessListResponse:
        """``GET .../story-runs/{run_id}/push-freshness`` (FK-10 §10.2.4b, AG3-147 AC5).

        Read-only projection of the Postgres-only ``push_freshness_records``
        read surface (one row per participating repo). Freshness / silence is
        INFORMATION only: reading it never triggers an ownership transition
        (AC5). Fail-closed on a non-Postgres backend (``ConfigError``, K5).
        """
        self._require_postgres_backend_on_first_use()
        from agentkit.backend.state_backend.story_closure_store import (
            list_push_freshness_records_global,
        )

        records = list_push_freshness_records_global(project_key, story_id, run_id)
        return PushFreshnessListResponse(
            freshness=[
                PushFreshnessView(
                    repo_id=record.repo_id,
                    last_reported_head_sha=record.last_reported_head_sha,
                    last_pushed_head_sha=record.last_pushed_head_sha,
                    last_reported_at=record.last_reported_at,
                    last_sync_point_id=record.last_sync_point_id,
                    last_command_id=record.last_command_id,
                    backlog=record.backlog,
                    backlog_detail=record.backlog_detail,
                )
                for record in records
            ]
        )

    def confirm_push_ownership(
        self,
        run_id: str,
        *,
        project_key: str,
        story_id: str,
        session_id: str,
    ) -> PushOwnershipConfirmation:
        """``GET .../story-runs/{run_id}/push-ownership`` (FK-15 §15.5.4, AG3-147 AC6).

        The bounded, fresh online-ownership check the official Edge-Push-Gate
        runs immediately before a ``story/*`` push. Read-only (Rule 13: a read
        takes no lock/claim); it reuses the EXACT
        :func:`evaluate_ownership_admission` rule the mutating fences apply, so
        the gate can never diverge from the write fence. It consults NO ACTIVE
        bundle by design -- a stale bundle grants no push (the FK-56 §56.9a
        re-sync fallback does not apply to the push path, FK-15 §15.5.4).
        Fail-closed on a non-Postgres backend (``ConfigError``, K5).
        """
        self._require_postgres_backend_on_first_use()
        active_record = self._repo.load_active_ownership(project_key, story_id)
        admission = self._evaluate_run_admission(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            session_id=session_id,
            command_id="push_ownership_confirmation",
        )
        write_auth = authorize_story_ref_write(
            active_owner_session_id=(active_record.owner_session_id if active_record is not None else None),
            active_ownership_epoch=(active_record.ownership_epoch if active_record is not None else None),
            requesting_session_id=session_id,
            requesting_ownership_epoch=(
                active_record.ownership_epoch if active_record is not None and active_record.owner_session_id == session_id else 0
            ),
        )
        rejection_detail = admission.rejection_reason.value if admission.rejection_reason else write_auth.detail
        return PushOwnershipConfirmation(
            run_id=run_id,
            owner_confirmed=admission.admitted and write_auth.granted,
            detail=(
                "the server confirms this session as the current run owner and story/* service-identity write is released"
                if admission.admitted and write_auth.granted
                else (f"the server does not confirm this session as the current run owner ({rejection_detail})")
            ),
        )

    def submit_command_result(
        self,
        command_id: str,
        request: EdgeCommandResultRequest,
    ) -> EdgeCommandMutationResult:
        """``POST .../commands/{command_id}/result`` (FK-91 §91.1b, AG3-145 AC2/AC3).

        Story-serialized (Rule 13, the AG3-141 object-claim helper acquired
        BEFORE apply) and Rule-15 ownership-fenced against the ACTIVE
        ownership record at commit time (AG3-142 fence surface reused
        verbatim, no TOCTOU): an ex-owner / epoch-drift result is rejected
        409/403 with the ``ownership_transferred`` payload -- WITHOUT any
        state write. An unknown ``command_id`` or a double-completion under a
        DIFFERENT ``op_id`` is deterministically rejected; a replay of the
        SAME ``op_id`` that already terminated the command is idempotent.
        """
        self._require_postgres_backend_on_first_use()
        existing = self._edge_command_repo.load_command(command_id)
        not_found = existing is None or (existing.project_key != request.project_key or existing.story_id != request.story_id)
        if not_found:
            return EdgeCommandMutationResult(
                status="rejected",
                command_id=command_id,
                op_id=request.op_id,
                error_code="edge_command_not_found",
            )
        assert existing is not None  # noqa: S101 -- `not_found` excluded None above
        if existing.result_op_id is not None:
            if existing.result_op_id == request.op_id:
                return EdgeCommandMutationResult(
                    status="replayed",
                    command_id=command_id,
                    op_id=request.op_id,
                )
            return EdgeCommandMutationResult(
                status="rejected",
                command_id=command_id,
                op_id=request.op_id,
                error_code="edge_command_already_resolved",
            )

        admission = self._evaluate_run_admission(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=existing.run_id,
            session_id=request.session_id,
            command_id="edge_command_result",
        )
        if not admission.admitted:
            return self._edge_command_ownership_admission_rejection(
                admission,
                command_id=command_id,
                op_id=request.op_id,
            )
        assert admission.active_record is not None  # noqa: S101 -- admitted implies a record
        expected_ownership_epoch = admission.active_record.ownership_epoch

        object_conflict = self._acquire_object_claim(
            project_key=request.project_key,
            story_id=request.story_id,
            op_id=request.op_id,
        )
        if object_conflict is not None:
            return EdgeCommandMutationResult(
                status="rejected",
                command_id=command_id,
                op_id=request.op_id,
                error_code=object_conflict.error_code,
                retry_after_seconds=object_conflict.retry_after_seconds,
            )
        return self._commit_command_result(
            existing,
            request=request,
            command_id=command_id,
            expected_ownership_epoch=expected_ownership_epoch,
        )

    def _commit_command_result(
        self,
        existing: EdgeCommandRecord,
        *,
        request: EdgeCommandResultRequest,
        command_id: str,
        expected_ownership_epoch: int,
    ) -> EdgeCommandMutationResult:
        """Commit the fenced command-result after the object claim is held.

        Extracted from :meth:`submit_command_result` for cohesion: owns the
        claim-release discipline (non-best-effort on a handled outcome,
        best-effort on an unexpected exception -- mirrors ``_mutate_phase``).
        """
        now = self._now_fn()
        result_status: Literal["completed", "failed"] = (
            "failed" if request.result.result_type in runtime_constants.EDGE_COMMAND_FAILURE_RESULT_TYPES else "completed"
        )
        op_record = ControlPlaneOperationRecord(
            op_id=request.op_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=existing.run_id,
            session_id=request.session_id,
            operation_kind="edge_command_result",
            phase=None,
            status="committed",
            response_payload={
                "status": result_status,
                "command_id": command_id,
                "op_id": request.op_id,
            },
            created_at=now,
            updated_at=now,
        )
        try:
            self._edge_command_repo.commit_result(
                op_record,
                command_id=command_id,
                result_status=result_status,
                completed_at=now,
                result_op_id=request.op_id,
                result_type=request.result.result_type,
                result_payload=request.result.model_dump(mode="json"),
                expected_ownership_epoch=expected_ownership_epoch,
            )
            self._project_push_freshness_from_result(existing, request=request, now=now)
            self._resolve_push_barrier_from_result(existing, request=request, now=now)
        except OwnershipFenceViolationError as exc:
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return self._edge_command_fence_violation_rejection(
                exc,
                command_id=command_id,
                op_id=request.op_id,
            )
        except (ControlPlaneClaimCollisionError, EdgeCommandNotOpenError):
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return EdgeCommandMutationResult(
                status="rejected",
                command_id=command_id,
                op_id=request.op_id,
                error_code="edge_command_already_resolved",
            )
        except BaseException:
            self._release_object_claim_best_effort(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            raise
        self._release_object_claim(
            project_key=request.project_key,
            story_id=request.story_id,
            op_id=request.op_id,
        )
        return EdgeCommandMutationResult(
            status="completed",
            command_id=command_id,
            op_id=request.op_id,
        )

    def _project_push_freshness_from_result(
        self,
        existing: EdgeCommandRecord,
        *,
        request: EdgeCommandResultRequest,
        now: datetime,
    ) -> None:
        """Project a ``sync_push`` result into the push-freshness read model (AC3/AC4).

        The LOAD-BEARING writer of the push-freshness / backlog table
        (In-Scope #3): a ``push_status_report`` advances the pushed head SHA (or
        raises a visible backlog on ``behind_remote``) per ``(story, run, repo)``.
        Runs INSIDE the fenced command-result commit (behind the Postgres guard,
        K5), so it inherits the Rule-15 ownership fence -- an ex-owner's result
        never updates the freshness. Freshness is INFORMATION only; it triggers
        No ownership effect (AC5). A ``sync_push`` ``command_error`` records a
        visible backlog as well, so a post-gate git failure cannot leave a stale
        successful freshness row standing.
        """
        result = request.result
        if existing.command_kind != "sync_push":
            return
        repo_id = _sync_push_result_repo_id(existing, result)
        if repo_id is None:
            return
        from agentkit.backend.state_backend.story_closure_store import (
            load_push_freshness_record_global,
            upsert_push_freshness_record_global,
        )

        previous = load_push_freshness_record_global(request.project_key, request.story_id, existing.run_id, repo_id)
        if result.result_type == "push_status_report":
            reported_head_sha = result.head_sha
            push_outcome = result.push_outcome
        else:
            reported_head_sha = None
            push_outcome = "behind_remote"
        sync_point_id = _sync_point_id_from_sync_push_command(existing.command_id, run_id=existing.run_id, repo_id=repo_id)
        record = project_push_freshness(
            previous,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=existing.run_id,
            repo_id=repo_id,
            reported_head_sha=reported_head_sha,
            push_outcome=push_outcome,
            reported_at=now,
            sync_point_id=sync_point_id,
            command_id=existing.command_id,
        )
        upsert_push_freshness_record_global(record)

    def _resolve_push_barrier_from_result(
        self,
        existing: EdgeCommandRecord,
        *,
        request: EdgeCommandResultRequest,
        now: datetime,
    ) -> None:
        """Resolve a pending boundary verdict from a confirming ``sync_push`` return."""
        binding = _push_barrier_result_binding(existing, request.result)
        if binding is None:
            return
        repo_id, boundary_type, boundary_id, boundary_epoch = binding
        current = self._load_boundary_verdict(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=existing.run_id,
            boundary_type=boundary_type,
            boundary_id=boundary_id,
            repo_id=repo_id,
        )
        if current is None or _push_barrier_result_is_fenced(
            current, existing, request.result, command_boundary_epoch=boundary_epoch
        ):
            return
        result = request.result
        if result.result_type != "push_status_report":
            self._upsert_boundary_verdict(_sync_push_failed_barrier_verdict(current, updated_at=now))
            return
        sync_point_id = push_barrier_lifecycle.boundary_sync_point_id(boundary_type, boundary_id, current.boundary_epoch)
        self._upsert_boundary_verdict(
            self._push_status_barrier_verdict(
                current,
                result,
                repo_id=repo_id,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=existing.run_id,
                sync_point_id=sync_point_id,
                updated_at=now,
            )
        )

    def _push_status_barrier_verdict(
        self,
        current: PushBarrierVerdict,
        result: EdgeCommandResultPayload,
        *,
        repo_id: str,
        project_key: str,
        story_id: str,
        run_id: str,
        sync_point_id: str,
        updated_at: datetime,
    ) -> PushBarrierVerdict:
        """Resolve one pending verdict from a fenced ``push_status_report``."""
        assert result.result_type == "push_status_report"  # noqa: S101
        server_resolved, server_head = self._server_read_for_push_result(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            repo_id=repo_id,
            required_sync_point_id=sync_point_id,
        )
        repo_verdict = evaluate_repo_push(
            RepoPushVerificationInput(
                repo_id=repo_id,
                edge_report_present=True,
                edge_reported_pushed=result.push_outcome == "pushed",
                edge_reported_head_sha=result.head_sha,
                server_ref_resolved=server_resolved,
                server_head_sha=server_head,
                edge_report_sync_point_id=sync_point_id,
                required_sync_point_id=sync_point_id,
            )
        )
        return push_barrier_lifecycle.replace_push_barrier_verdict(
            current,
            expected_head_sha=result.head_sha,
            server_head_sha=server_head,
            status=(PushBarrierVerdictStatus.PASSED if repo_verdict.verified else PushBarrierVerdictStatus.BLOCKED_BACKLOG),
            updated_at=updated_at,
            resolved_at=updated_at,
            status_detail=repo_verdict.detail,
        )

    def _server_read_for_push_result(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        repo_id: str,
        required_sync_point_id: str,
    ) -> tuple[bool, str | None]:
        """Return the backend-owned server read used for result resolution."""
        server_input = self._server_input_for_push_result(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            repo_id=repo_id,
            required_sync_point_id=required_sync_point_id,
        )
        if server_input is None:
            return False, None
        return server_input.server_ref_resolved, server_input.server_head_sha

    def _server_input_for_push_result(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        repo_id: str,
        required_sync_point_id: str,
    ) -> RepoPushVerificationInput | None:
        """Return server-ref evidence for one repo during result resolution."""
        inputs = self._collect_push_barrier_inputs(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            required_sync_point_id=required_sync_point_id,
        )
        if inputs is None:
            return None
        for inp in inputs:
            if inp.repo_id == repo_id:
                return inp
        return None

    def _edge_command_ownership_admission_rejection(
        self,
        admission: OwnershipAdmission,
        *,
        command_id: str,
        op_id: str,
    ) -> EdgeCommandMutationResult:
        """Build the ex-owner rejection from a rejected :class:`OwnershipAdmission`.

        Mirrors ``_ownership_admission_rejection`` (phase mutations) but
        returns :class:`EdgeCommandMutationResult`: ONLY the
        ``OWNERSHIP_TRANSFERRED`` reason carries the rich structured payload.
        """
        if admission.rejection_reason is OwnershipRejectionReason.FREEZE_ACTIVE:
            return EdgeCommandMutationResult(
                status="rejected",
                command_id=command_id,
                op_id=op_id,
                error_code=ERROR_CODE_STORY_FROZEN,
            )
        if admission.rejection_reason is not OwnershipRejectionReason.OWNERSHIP_TRANSFERRED:
            return EdgeCommandMutationResult(
                status="rejected",
                command_id=command_id,
                op_id=op_id,
                error_code="edge_command_not_admitted",
            )
        record = admission.active_record
        assert record is not None  # noqa: S101 -- OWNERSHIP_TRANSFERRED always carries one
        return EdgeCommandMutationResult(
            status="rejected",
            command_id=command_id,
            op_id=op_id,
            error_code=ERROR_CODE_OWNERSHIP_TRANSFERRED,
            ownership_conflict=OwnershipTransferredDetail(
                reason="ownership_transferred",
                new_owner_session_id=record.owner_session_id,
                new_ownership_epoch=record.ownership_epoch,
                transferred_at=record.acquired_at,
            ),
        )

    def _edge_command_fence_violation_rejection(
        self,
        exc: OwnershipFenceViolationError,
        *,
        command_id: str,
        op_id: str,
    ) -> EdgeCommandMutationResult:
        """Build the ex-owner rejection from a commit-time fence violation (AG3-142).

        Mirrors ``_ownership_fence_violation_rejection`` but returns
        :class:`EdgeCommandMutationResult`. ``detail`` carries the CURRENT
        conflicting owner read within the SAME rolled-back transaction (no
        TOCTOU); ``None`` values mean no active record exists at all (never a
        genuine transfer) -- a plain fail-closed rejection.
        """
        new_owner = exc.detail.get("current_owner_session_id")
        new_epoch = exc.detail.get("current_ownership_epoch")
        transferred_at = exc.detail.get("transferred_at")
        if exc.detail.get("error_code") == ERROR_CODE_STORY_FROZEN:
            return EdgeCommandMutationResult(
                status="rejected",
                command_id=command_id,
                op_id=op_id,
                error_code=ERROR_CODE_STORY_FROZEN,
            )
        if not isinstance(new_owner, str) or not isinstance(new_epoch, int) or not isinstance(transferred_at, str):
            return EdgeCommandMutationResult(
                status="rejected",
                command_id=command_id,
                op_id=op_id,
                error_code="edge_command_not_admitted",
            )
        return EdgeCommandMutationResult(
            status="rejected",
            command_id=command_id,
            op_id=op_id,
            error_code=ERROR_CODE_OWNERSHIP_TRANSFERRED,
            ownership_conflict=OwnershipTransferredDetail(
                reason="ownership_transferred",
                new_owner_session_id=new_owner,
                new_ownership_epoch=new_epoch,
                transferred_at=datetime.fromisoformat(transferred_at),
            ),
        )
