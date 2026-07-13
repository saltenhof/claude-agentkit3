"""Unit tests for the Edge-Command-Queue runtime wiring (FK-91 §91.1b, AG3-145).

DI-injected fakes -- no database. Exercises AC1 (GET Ack + fail-closed session
scoping), AC2 (the AG3-141 object-claim helper acquired before apply; replay /
unknown-command / double-completion rejection) and AC3 (Rule-15 fence
rejection, ownership_transferred payload, NO state write).
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.backend.control_plane.models import (
    EdgeCommandResultRequest,
    MergeLocalRepoReport,
    MergeLocalReport,
    TakeoverErrorResult,
    WorktreeReport,
)
from agentkit.backend.control_plane.ownership import OwnershipAcquisition, OwnershipStatus
from agentkit.backend.control_plane.records import EdgeCommandRecord, RunOwnershipRecord
from agentkit.backend.control_plane.repository import (
    ControlPlaneRuntimeRepository,
    EdgeCommandRepository,
    ObjectMutationClaimRepository,
)
from agentkit.backend.control_plane.runtime import (
    ControlPlaneRuntimeService,
    _default_di_edge_command_repository,
)
from agentkit.backend.core_types.verify_evidence import (
    CollectVerifyEvidenceCommandPayload,
    VerifyEvidenceFile,
    VerifyEvidenceObservation,
    VerifyEvidenceObservationStatus,
    VerifyEvidenceReport,
    VerifyEvidenceRepository,
    VerifyEvidenceRequest,
)
from agentkit.backend.exceptions import OwnershipFenceViolationError

_NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


def _ownership_record(
    *,
    owner: str = "sess-A",
    epoch: int = 1,
    run_id: str = "run-1",
    story_id: str = "AG3-100",
) -> RunOwnershipRecord:
    return RunOwnershipRecord(
        project_key="tenant-a",
        story_id=story_id,
        run_id=run_id,
        owner_session_id=owner,
        ownership_epoch=epoch,
        status=OwnershipStatus.ACTIVE,
        acquired_via=OwnershipAcquisition.SETUP,
        acquired_at=_NOW,
        audit_ref="audit:x",
    )


def _command(*, status: str = "created", **overrides: object) -> EdgeCommandRecord:
    defaults: dict[str, object] = {
        "command_id": "cmd-1",
        "project_key": "tenant-a",
        "story_id": "AG3-100",
        "run_id": "run-1",
        "session_id": "sess-A",
        "command_kind": "provision_worktree",
        "payload": {},
        "status": status,
        "ownership_epoch": 1,
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return EdgeCommandRecord(**defaults)  # type: ignore[arg-type]


def _service(
    *,
    active: RunOwnershipRecord | None,
    edge_command_repository: EdgeCommandRepository,
    object_claim_repository: ObjectMutationClaimRepository | None = None,
) -> ControlPlaneRuntimeService:
    return ControlPlaneRuntimeService(
        repository=ControlPlaneRuntimeRepository(
            load_active_ownership=lambda pk, sid: active,  # noqa: ARG005
        ),
        edge_command_repository=edge_command_repository,
        object_claim_repository=object_claim_repository,
    )


def _success_request(*, op_id: str = "op-1") -> EdgeCommandResultRequest:
    return EdgeCommandResultRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-A",
        op_id=op_id,
        result=WorktreeReport(
            repo_id="repo-a", outcome="provisioned", worktree_root="/wt/AG3-100",
        ),
    )


# ---------------------------------------------------------------------------
# AG3-147 AC6: bounded online-ownership check for the Edge-Push-Gate
# (read-only, reuses the exact evaluate_ownership_admission write-fence rule)
# ---------------------------------------------------------------------------


def _confirm(service: ControlPlaneRuntimeService, *, session_id: str = "sess-A",
             run_id: str = "run-1") -> bool:
    return service.confirm_push_ownership(
        run_id, project_key="tenant-a", story_id="AG3-100", session_id=session_id,
    ).owner_confirmed


def test_confirm_push_ownership_admits_the_current_owner() -> None:
    service = _service(
        active=_ownership_record(owner="sess-A", run_id="run-1"),
        edge_command_repository=_default_di_edge_command_repository(),
    )
    assert _confirm(service, session_id="sess-A", run_id="run-1") is True


def test_confirm_push_ownership_denies_an_ex_owner() -> None:
    """AC7 (gate half): after a transfer the ex-owner is NOT confirmed online."""
    service = _service(
        active=_ownership_record(owner="sess-B", run_id="run-1"),
        edge_command_repository=_default_di_edge_command_repository(),
    )
    assert _confirm(service, session_id="sess-A", run_id="run-1") is False


def test_confirm_push_ownership_denies_when_no_active_record() -> None:
    service = _service(
        active=None, edge_command_repository=_default_di_edge_command_repository()
    )
    assert _confirm(service, session_id="sess-A", run_id="run-1") is False


def test_confirm_push_ownership_denies_a_run_mismatch() -> None:
    service = _service(
        active=_ownership_record(owner="sess-A", run_id="run-2"),
        edge_command_repository=_default_di_edge_command_repository(),
    )
    assert _confirm(service, session_id="sess-A", run_id="run-1") is False


# ---------------------------------------------------------------------------
# AC1: GET list_and_ack_open_commands -- Ack + fail-closed session scoping
# ---------------------------------------------------------------------------


def test_get_open_commands_returns_open_commands_and_marks_delivered() -> None:
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(_command(payload={"repo_id": "repo-a"}))
    service = _service(active=None, edge_command_repository=edge_repo)

    response = service.list_and_ack_open_commands(
        "run-1", project_key="tenant-a", session_id="sess-A",
    )

    assert len(response.commands) == 1
    view = response.commands[0]
    assert view.command_id == "cmd-1"
    assert view.command_kind == "provision_worktree"
    assert view.payload == {"repo_id": "repo-a"}
    stored = edge_repo.load_command("cmd-1")
    assert stored is not None
    assert stored.status == "delivered"
    assert stored.delivered_at is not None


def test_get_open_commands_foreign_session_gets_nothing() -> None:
    """AC1: a foreign session's query returns none of another session's commands."""
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(_command())
    service = _service(active=None, edge_command_repository=edge_repo)

    response = service.list_and_ack_open_commands(
        "run-1", project_key="tenant-a", session_id="sess-FOREIGN",
    )

    assert response.commands == []
    stored = edge_repo.load_command("cmd-1")
    assert stored is not None
    assert stored.status == "created"  # untouched -- the foreign query never acked it


def test_get_open_commands_takes_no_object_mutation_claim() -> None:
    """FK-91 §91.1a Rule 13: the read takes no lock/claim."""
    claim_calls: list[str] = []
    object_claim_repo = ObjectMutationClaimRepository(
        acquire_claim=lambda **kwargs: bool(claim_calls.append(kwargs["op_id"])) or True,
    )
    edge_repo = _default_di_edge_command_repository()
    service = _service(
        active=None,
        edge_command_repository=edge_repo,
        object_claim_repository=object_claim_repo,
    )

    service.list_and_ack_open_commands("run-1", project_key="tenant-a", session_id="sess-A")

    assert claim_calls == []


# ---------------------------------------------------------------------------
# AC2: POST submit_command_result -- idempotency + the AG3-141 claim helper
# ---------------------------------------------------------------------------


def test_submit_result_unknown_command_id_is_rejected_not_found() -> None:
    edge_repo = _default_di_edge_command_repository()
    service = _service(active=_ownership_record(), edge_command_repository=edge_repo)

    result = service.submit_command_result("cmd-missing", _success_request())

    assert result.status == "rejected"
    assert result.error_code == "edge_command_not_found"


def test_submit_result_success_acquires_and_releases_the_object_claim() -> None:
    """AC2: the AG3-141 object-claim helper is acquired BEFORE apply, released after."""
    claim_calls: list[str] = []
    release_calls: list[str] = []
    object_claim_repo = ObjectMutationClaimRepository(
        acquire_claim=lambda **kwargs: bool(claim_calls.append(kwargs["op_id"])) or True,
        release_claim=lambda pk, scope, key, op_id: bool(release_calls.append(op_id)) or True,
    )
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(_command(status="delivered"))
    service = _service(
        active=_ownership_record(),
        edge_command_repository=edge_repo,
        object_claim_repository=object_claim_repo,
    )

    result = service.submit_command_result("cmd-1", _success_request())

    assert result.status == "completed"
    assert result.command_id == "cmd-1"
    assert claim_calls == ["op-1"]
    assert release_calls == ["op-1"]
    stored = edge_repo.load_command("cmd-1")
    assert stored is not None
    assert stored.status == "completed"
    assert stored.result_op_id == "op-1"
    assert stored.result_type == "worktree_report"


def test_submit_result_replays_the_same_op_id_idempotently() -> None:
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(
        _command(
            status="completed",
            completed_at=_NOW,
            result_op_id="op-1",
            result_type="worktree_report",
            result_payload={},
        )
    )
    service = _service(active=_ownership_record(), edge_command_repository=edge_repo)

    result = service.submit_command_result("cmd-1", _success_request(op_id="op-1"))

    assert result.status == "replayed"


def test_submit_result_double_completion_different_op_id_is_rejected() -> None:
    """AC2: a double-completion under a DIFFERENT op_id is deterministically rejected."""
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(
        _command(
            status="completed",
            completed_at=_NOW,
            result_op_id="op-1",
            result_type="worktree_report",
            result_payload={},
        )
    )
    service = _service(active=_ownership_record(), edge_command_repository=edge_repo)

    result = service.submit_command_result("cmd-1", _success_request(op_id="op-2"))

    assert result.status == "rejected"
    assert result.error_code == "edge_command_already_resolved"


def test_submit_result_busy_object_claim_is_rejected_with_retry_after() -> None:
    """K4 (IMPL-016): a busy per-Story claim is a deterministic 409-shaped rejection."""
    object_claim_repo = ObjectMutationClaimRepository(acquire_claim=lambda **kwargs: False)
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(_command(status="delivered"))
    service = _service(
        active=_ownership_record(),
        edge_command_repository=edge_repo,
        object_claim_repository=object_claim_repo,
    )

    result = service.submit_command_result("cmd-1", _success_request())

    assert result.status == "rejected"
    assert result.error_code == "conflict"
    assert result.retry_after_seconds is not None


def test_submit_result_takeover_error_result_terminates_as_failed() -> None:
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(_command(status="delivered", command_kind="preflight_probe"))
    service = _service(active=_ownership_record(), edge_command_repository=edge_repo)
    request = EdgeCommandResultRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-A",
        op_id="op-1",
        result=TakeoverErrorResult(
            result_type="local_stale_or_dirty_takeover_target", repo_id="repo-a",
        ),
    )

    result = service.submit_command_result("cmd-1", request)

    assert result.status == "completed"
    stored = edge_repo.load_command("cmd-1")
    assert stored is not None
    assert stored.status == "failed"
    assert stored.result_type == "local_stale_or_dirty_takeover_target"


# ---------------------------------------------------------------------------
# AC3: Rule-15 ownership fence -- ex-owner / epoch-drift, NO state write
# ---------------------------------------------------------------------------


def test_submit_result_no_active_ownership_record_is_rejected_untouched() -> None:
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(_command(status="delivered"))
    service = _service(active=None, edge_command_repository=edge_repo)

    result = service.submit_command_result("cmd-1", _success_request())

    assert result.status == "rejected"
    assert result.error_code == "edge_command_not_admitted"
    stored = edge_repo.load_command("cmd-1")
    assert stored is not None
    assert stored.status == "delivered"  # untouched -- NO state write


def test_submit_result_ex_owner_is_rejected_with_ownership_transferred_untouched() -> None:
    """AC3: the EARLY admission check rejects an ex-owner's call -- no state write."""
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(_command(status="delivered"))
    service = _service(
        active=_ownership_record(owner="sess-NEW-OWNER", epoch=2),
        edge_command_repository=edge_repo,
    )

    result = service.submit_command_result("cmd-1", _success_request())

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-NEW-OWNER"
    assert result.ownership_conflict.new_ownership_epoch == 2
    stored = edge_repo.load_command("cmd-1")
    assert stored is not None
    assert stored.status == "delivered"  # untouched -- NO state write


def test_merge_local_result_from_ex_owner_has_no_control_effect() -> None:
    """AG3-152 AC6: Rule-15 fencing applies unchanged to merge_local reports."""
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(
        _command(status="delivered", command_kind="merge_local")
    )
    service = _service(
        active=_ownership_record(owner="sess-NEW-OWNER", epoch=2),
        edge_command_repository=edge_repo,
    )
    request = EdgeCommandResultRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-A",
        op_id="op-merge",
        result=MergeLocalReport(
            outcome="merged",
            escalated=False,
            merged_main_sha="a" * 40,
            repositories=[
                MergeLocalRepoReport(
                    repo_id="repo-a", outcome="merged", merged=True
                )
            ],
        ),
    )

    result = service.submit_command_result("cmd-1", request)

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    stored = edge_repo.load_command("cmd-1")
    assert stored is not None
    assert stored.status == "delivered"


def test_verify_evidence_echo_mismatch_never_terminalizes_command() -> None:
    """Batch/generation/candidate/request correlation is a pre-commit fence."""
    payload = CollectVerifyEvidenceCommandPayload(
        stage="base_collection",
        story_id="AG3-100",
        project_key="tenant-a",
        run_id="run-1",
        implementation_attempt=1,
        batch_id="a" * 64,
        generation="b" * 64,
        candidate_digest="c" * 64,
        request_digest="d" * 64,
        preflight_template_version=1,
        deadline_at=_NOW,
        repositories=(
            VerifyEvidenceRepository(repo_id="repo-a", expected_head_sha="e" * 40),
        ),
        spawn_worktree_repo="repo-a",
    )
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(
        _command(
            status="delivered",
            command_kind="collect_verify_evidence",
            payload=payload.model_dump(mode="json"),
        )
    )
    service = _service(active=_ownership_record(), edge_command_repository=edge_repo)
    request = EdgeCommandResultRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-A",
        op_id="op-mismatch",
        result=VerifyEvidenceReport(
            stage="base_collection",
            batch_id="f" * 64,
            generation=payload.generation,
            candidate_digest=payload.candidate_digest,
            request_digest=payload.request_digest,
        ),
    )

    result = service.submit_command_result("cmd-1", request)

    assert result.status == "rejected"
    assert result.error_code == "verify_evidence_result_mismatch"
    stored = edge_repo.load_command("cmd-1")
    assert stored is not None and stored.status == "delivered"


def test_verify_evidence_result_from_ex_owner_has_no_bundle_effect() -> None:
    """The sanctioned Rule-15 surface rejects the old epoch before commit."""
    payload = CollectVerifyEvidenceCommandPayload(
        stage="base_collection",
        story_id="AG3-100",
        project_key="tenant-a",
        run_id="run-1",
        implementation_attempt=1,
        batch_id="a" * 64,
        generation="b" * 64,
        candidate_digest="c" * 64,
        request_digest="d" * 64,
        preflight_template_version=1,
        deadline_at=_NOW,
        repositories=(
            VerifyEvidenceRepository(repo_id="repo-a", expected_head_sha="e" * 40),
        ),
        spawn_worktree_repo="repo-a",
    )
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(
        _command(
            status="delivered",
            command_kind="collect_verify_evidence",
            payload=payload.model_dump(mode="json"),
        )
    )
    service = _service(
        active=_ownership_record(owner="sess-NEW-OWNER", epoch=2),
        edge_command_repository=edge_repo,
    )
    request = EdgeCommandResultRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-A",
        op_id="op-old-owner-evidence",
        result=VerifyEvidenceReport(
            stage="base_collection",
            batch_id=payload.batch_id,
            generation=payload.generation,
            candidate_digest=payload.candidate_digest,
            request_digest=payload.request_digest,
        ),
    )

    result = service.submit_command_result("cmd-1", request)

    assert result.error_code == "ownership_transferred"
    stored = edge_repo.load_command("cmd-1")
    assert stored is not None and stored.status == "delivered"


def test_dynamic_evidence_from_foreign_repo_never_terminalizes_command() -> None:
    """Every candidate must belong to the command's repository generation."""
    payload = CollectVerifyEvidenceCommandPayload(
        stage="dynamic_requests",
        story_id="AG3-100",
        project_key="tenant-a",
        run_id="run-1",
        implementation_attempt=1,
        batch_id="a" * 64,
        generation="b" * 64,
        candidate_digest="c" * 64,
        request_digest="d" * 64,
        preflight_template_version=1,
        deadline_at=_NOW,
        repositories=(
            VerifyEvidenceRepository(repo_id="repo-a", expected_head_sha="e" * 40),
        ),
        spawn_worktree_repo="repo-a",
        requests=(
            VerifyEvidenceRequest(
                request_index=0,
                request_type="NEED_FILE",
                target="src/context.py",
            ),
        ),
        preflight_requests=(),
        preflight_attempt_id="attempt-1",
        preflight_checkpoint_state="ready",
        preflight_request_hash="f" * 64,
        raw_preflight_response='{"requests":[]}',
        base_manifest={},
    )
    edge_repo = _default_di_edge_command_repository()
    edge_repo.insert_command(
        _command(
            status="delivered",
            command_kind="collect_verify_evidence",
            payload=payload.model_dump(mode="json"),
        )
    )
    service = _service(active=_ownership_record(), edge_command_repository=edge_repo)
    foreign = VerifyEvidenceFile.from_content(
        repo_id="foreign", path="src/context.py", content="SECRET = True\n"
    )
    request = EdgeCommandResultRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-A",
        op_id="op-foreign-repo",
        result=VerifyEvidenceReport(
            stage="dynamic_requests",
            batch_id=payload.batch_id,
            generation=payload.generation,
            candidate_digest=payload.candidate_digest,
            request_digest=payload.request_digest,
            observations=(
                VerifyEvidenceObservation(
                    request_index=0,
                    status=VerifyEvidenceObservationStatus.COLLECTED,
                    candidates=(foreign,),
                ),
            ),
        ),
    )

    result = service.submit_command_result("cmd-1", request)

    assert result.error_code == "verify_evidence_result_mismatch"
    stored = edge_repo.load_command("cmd-1")
    assert stored is not None and stored.status == "delivered"


def test_submit_result_commit_time_fence_violation_releases_claim_no_write() -> None:
    """AC3 (no TOCTOU): a LATE fence violation (at commit time) rejects with NO
    state write and releases the object claim (never leaked)."""
    release_calls: list[str] = []
    object_claim_repo = ObjectMutationClaimRepository(
        acquire_claim=lambda **kwargs: True,
        release_claim=lambda pk, scope, key, op_id: bool(release_calls.append(op_id)) or True,
    )

    def _raise_fence(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OwnershipFenceViolationError(
            "ownership fence violated",
            detail={
                "current_owner_session_id": "sess-HIJACK",
                "current_ownership_epoch": 2,
                "transferred_at": _NOW.isoformat(),
            },
        )

    edge_repo = EdgeCommandRepository(
        insert_command=lambda record: None,  # noqa: ARG005
        load_command=lambda command_id: _command(status="delivered"),  # noqa: ARG005
        list_and_ack_open_commands=lambda **kwargs: (),
        commit_result=_raise_fence,
    )
    service = _service(
        active=_ownership_record(),
        edge_command_repository=edge_repo,
        object_claim_repository=object_claim_repo,
    )

    result = service.submit_command_result("cmd-1", _success_request())

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-HIJACK"
    assert release_calls == ["op-1"]
