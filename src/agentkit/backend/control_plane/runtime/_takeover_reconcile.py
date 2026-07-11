"""Backend takeover-reconcile mutation and contested-freeze transition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    TakeoverErrorResult,
    TakeoverQuarantineDetail,
    TakeoverReconcileResponse,
    TakeoverReconcileResultView,
    TakeoverReconcileWorktreeRequest,
    WorktreeReport,
)
from agentkit.backend.control_plane.takeover_reconcile import (
    TakeoverReconcileClassification,
    TakeoverReconcileEvidence,
    classify_takeover_reconcile,
)
from agentkit.backend.core_types.freeze import FreezeKind
from agentkit.backend.exceptions import OwnershipFenceViolationError
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    compute_body_hash,
)

from ._operation_records import (
    _object_claim_busy_rejection,
    _operation_record,
    _rejection_result,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane import object_claims
    from agentkit.backend.control_plane.ownership_fence import OwnershipAdmission
    from agentkit.backend.control_plane.push_sync import RepoPushVerificationInput
    from agentkit.backend.control_plane.records import TakeoverTransferRecord
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
    from agentkit.backend.state_backend.store.freeze_repository import (
        FreezeRepository,
        LocalFreezeJsonExport,
    )

_OPERATION_KIND = "takeover_reconcile_worktree"
_RESOLVER_COMMAND = "takeover_reconcile_clear"
_PHASE = "ownership"


class _TakeoverReconcileMixin:
    """Official reconcile endpoint runtime, composed onto the control-plane service."""

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository
        _freeze_repository: FreezeRepository
        _local_freeze_export: LocalFreezeJsonExport
        _now_fn: Callable[[], datetime]

        def _require_postgres_backend_on_first_use(self) -> None: ...
        def _sync_local_freeze_projection(self, story_id: str) -> None: ...
        def _collect_push_barrier_inputs(
            self,
            *,
            project_key: str,
            story_id: str,
            run_id: str,
            required_sync_point_id: str | None = None,
        ) -> tuple[RepoPushVerificationInput, ...] | None: ...
        def _evaluate_run_admission(
            self,
            *,
            project_key: str,
            story_id: str,
            session_id: str,
            run_id: str,
            command_id: str,
        ) -> OwnershipAdmission: ...
        def _ownership_admission_rejection(
            self,
            admission: OwnershipAdmission,
            *,
            op_id: str,
            operation_kind: str,
            run_id: str | None,
            phase: str | None,
            session_id: str,
        ) -> ControlPlaneMutationResult: ...
        def _acquire_object_claim(
            self, *, project_key: str, story_id: str, op_id: str
        ) -> object_claims.ObjectClaimConflict | None: ...
        def _release_object_claim(
            self, *, project_key: str, story_id: str, op_id: str
        ) -> None: ...
        def _release_object_claim_best_effort(
            self, *, project_key: str, story_id: str, op_id: str
        ) -> None: ...

    def reconcile_takeover_worktree(
        self,
        run_id: str,
        request: TakeoverReconcileWorktreeRequest,
    ) -> ControlPlaneMutationResult:
        """Validate per-repo evidence and clear or freeze the takeover state."""

        self._require_postgres_backend_on_first_use()
        body_hash = _request_body_hash(request, run_id=run_id)
        existing = self._repo.load_operation(request.op_id)
        if existing is not None and existing.status != "claimed":
            if existing.request_body_hash not in {None, body_hash}:
                from agentkit.backend.story_context_manager.errors import (
                    IdempotencyMismatchError,
                )

                raise IdempotencyMismatchError(
                    f"op_id {request.op_id!r} was previously used with a different "
                    "takeover reconcile request body",
                    detail={"op_id": request.op_id, "conflict": "body_hash_mismatch"},
                )
            return ControlPlaneMutationResult.model_validate(existing.response_payload)

        admission = self._evaluate_run_admission(
            project_key=request.project_key,
            story_id=request.story_id,
            session_id=request.session_id,
            run_id=run_id,
            command_id=_RESOLVER_COMMAND,
        )
        if not admission.admitted:
            return self._ownership_admission_rejection(
                admission,
                op_id=request.op_id,
                operation_kind=_OPERATION_KIND,
                run_id=run_id,
                phase=_PHASE,
                session_id=request.session_id,
            )
        active_record = admission.active_record
        if active_record is None:
            raise RuntimeError("admitted takeover reconcile lacks active ownership")
        conflict = self._acquire_object_claim(
            project_key=request.project_key,
            story_id=request.story_id,
            op_id=request.op_id,
        )
        if conflict is not None:
            return _object_claim_busy_rejection(
                op_id=request.op_id,
                operation_kind=_OPERATION_KIND,
                run_id=run_id,
                phase=_PHASE,
                conflict=conflict,
            )
        try:
            result = self._reconcile_under_claim(
                run_id=run_id,
                request=request,
                body_hash=body_hash,
                ownership_epoch=active_record.ownership_epoch,
            )
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return result
        except OwnershipFenceViolationError:
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return _rejection_result(
                op_id=request.op_id,
                operation_kind=_OPERATION_KIND,
                run_id=run_id,
                phase=_PHASE,
                reason="takeover reconcile obligation is no longer current",
            ).model_copy(update={"error_code": "takeover_reconcile_not_required"})
        except BaseException:
            self._release_object_claim_best_effort(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            raise

    def _reconcile_under_claim(
        self,
        *,
        run_id: str,
        request: TakeoverReconcileWorktreeRequest,
        body_hash: str,
        ownership_epoch: int,
    ) -> ControlPlaneMutationResult:
        now = self._now_fn()
        transfers = tuple(
            transfer
            for transfer in self._repo.list_takeover_history(
                request.project_key, request.story_id
            )
            if transfer.run_id == run_id
            and transfer.ownership_epoch == ownership_epoch
            and transfer.reconciled_at is None
        )
        if not transfers:
            return _rejection_result(
                op_id=request.op_id,
                operation_kind=_OPERATION_KIND,
                run_id=run_id,
                phase=_PHASE,
                reason="no unreconciled takeover transfer exists for the active epoch",
            ).model_copy(update={"error_code": "takeover_reconcile_not_required"})
        classifications = _classify_request(
            transfers,
            request=request,
            server_inputs=self._collect_push_barrier_inputs(
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
            ),
        )
        response = _response(classifications, request.quarantine_details)
        failure = next((item for item in classifications if not item.reconciled), None)
        if failure is not None:
            previous = self._freeze_repository.read_freeze(
                request.story_id,
                FreezeKind.CONTESTED_LOCAL_WRITES,
            )
            record = self._freeze_repository.set_freeze(
                request.story_id,
                frozen_at=now.isoformat(),
                freeze_reason=(
                    f"{failure.result_type}: repo={failure.repo_id}; {failure.detail}"
                ),
                freeze_version=(previous.freeze_version + 1 if previous else 1),
                kind=FreezeKind.CONTESTED_LOCAL_WRITES,
            )
            self._local_freeze_export.write_record(record)
            result = ControlPlaneMutationResult(
                status="failed",
                op_id=request.op_id,
                operation_kind=_OPERATION_KIND,
                run_id=run_id,
                phase=_PHASE,
                error_code=failure.result_type,
                takeover_reconcile=response,
            )
            self._repo.save_operation(
                _operation_record(
                    op_id=request.op_id,
                    project_key=request.project_key,
                    story_id=request.story_id,
                    run_id=run_id,
                    session_id=request.session_id,
                    operation_kind=_OPERATION_KIND,
                    phase=_PHASE,
                    result=result,
                    now=now,
                    request_body_hash=body_hash,
                )
            )
            return result
        result = ControlPlaneMutationResult(
            status="resolved",
            op_id=request.op_id,
            operation_kind=_OPERATION_KIND,
            run_id=run_id,
            phase=_PHASE,
            takeover_reconcile=response,
        )
        self._repo.commit_takeover_reconcile_clear(
            _operation_record(
                op_id=request.op_id,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
                session_id=request.session_id,
                operation_kind=_OPERATION_KIND,
                phase=_PHASE,
                result=result,
                now=now,
                request_body_hash=body_hash,
            ),
            ownership_epoch=ownership_epoch,
            reconciled_at=now,
            reconcile_ref=f"takeover_reconcile:{request.op_id}",
        )
        self._sync_local_freeze_projection(request.story_id)
        return result


def _classify_request(
    transfers: tuple[TakeoverTransferRecord, ...],
    *,
    request: TakeoverReconcileWorktreeRequest,
    server_inputs: tuple[RepoPushVerificationInput, ...] | None,
) -> tuple[TakeoverReconcileClassification, ...]:
    reports = {report.repo_id: report for report in request.results}
    duplicates = len(reports) != len(request.results)
    remote_heads = {
        item.repo_id: item.server_head_sha
        for item in server_inputs or ()
        if item.server_ref_resolved
    }
    classifications: list[TakeoverReconcileClassification] = []
    for transfer in transfers:
        report = None if duplicates else reports.get(transfer.repo_id)
        classifications.append(
            classify_takeover_reconcile(
                _evidence(transfer, report=report, remote_head=remote_heads.get(transfer.repo_id))
            )
        )
    expected = {transfer.repo_id for transfer in transfers}
    for unexpected in sorted(set(reports) - expected):
        classifications.append(
            TakeoverReconcileClassification(
                repo_id=unexpected,
                result_type="contested_local_writes",
                detail="result names a repository outside the active transfer set",
            )
        )
    return tuple(classifications)


def _evidence(
    transfer: TakeoverTransferRecord,
    *,
    report: WorktreeReport | TakeoverErrorResult | None,
    remote_head: str | None,
) -> TakeoverReconcileEvidence:
    if isinstance(report, WorktreeReport):
        return TakeoverReconcileEvidence(
            repo_id=transfer.repo_id,
            takeover_base_sha=transfer.takeover_base_sha,
            remote_head_sha=remote_head,
            worktree_head_sha=report.head_sha,
            marker_present=report.marker_present,
            reconcile_succeeded=report.outcome in {"provisioned", "no_op"},
        )
    return TakeoverReconcileEvidence(
        repo_id=transfer.repo_id,
        takeover_base_sha=transfer.takeover_base_sha,
        remote_head_sha=remote_head,
        worktree_head_sha=None,
        marker_present=False,
        reconcile_succeeded=False,
        target_stale_or_dirty=(
            isinstance(report, TakeoverErrorResult)
            and report.result_type == "local_stale_or_dirty_takeover_target"
        ),
        failure_detail=(report.detail if isinstance(report, TakeoverErrorResult) else "result missing or duplicated"),
    )


def _response(
    classifications: tuple[TakeoverReconcileClassification, ...],
    quarantine_details: list[TakeoverQuarantineDetail],
) -> TakeoverReconcileResponse:
    details = {detail.repo_id: detail for detail in quarantine_details}
    return TakeoverReconcileResponse(
        results=[
            TakeoverReconcileResultView(
                repo_id=item.repo_id,
                result_type=item.result_type,
                detail=item.detail,
                quarantine_detail=details.get(item.repo_id),
            )
            for item in classifications
        ]
    )


def _request_body_hash(request: TakeoverReconcileWorktreeRequest, *, run_id: str) -> str:
    payload = dict(request.model_dump(mode="json"))
    payload["__run_id"] = run_id
    payload["__operation_kind"] = _OPERATION_KIND
    return compute_body_hash(payload)


__all__ = ["_TakeoverReconcileMixin"]
