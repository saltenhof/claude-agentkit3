from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from agentkit.backend.control_plane.ownership import OwnershipStatus
from agentkit.backend.control_plane.records import (
    BindingDeleteScope,
    ControlPlaneOperationRecord,
    SessionRunBindingRecord,
)
from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
from agentkit.backend.governance.principal_capabilities.principals import Principal
from agentkit.backend.story_exit import (
    AdmissibilityAssessment,
    AlternativeReview,
    ExitClass,
    ExitReason,
    ExitRunState,
    StoryExitError,
    StoryExitRecord,
    StoryExitRequest,
    StoryExitService,
    TerminalState,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord


NOW = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)


@dataclass
class _Deactivation:
    restored_to_ai_augmented: bool = True


class _Governance:
    def __init__(self, *, restored: bool = True) -> None:
        self.calls: list[str] = []
        self.restored = restored

    def deactivate_locks(self, story_id: str) -> _Deactivation:
        self.calls.append(story_id)
        return _Deactivation(restored_to_ai_augmented=self.restored)


class _StoryService:
    def __init__(
        self,
        *,
        fail_before_cancel: bool = False,
        returned_status: str = "Cancelled",
    ) -> None:
        self.status = "In Progress"
        self.calls: list[str] = []
        self.fail_before_cancel = fail_before_cancel
        self.returned_status = returned_status

    def administratively_cancel_for_story_exit(
        self,
        story_display_id: str,
        *,
        story_exit_record: object,
        story_exit_operation_committed: bool,
        principal: object,
        op_id: str,
    ) -> object:
        del story_display_id, story_exit_record, op_id
        if self.fail_before_cancel:
            raise RuntimeError("crash before administrative cancel")
        assert story_exit_operation_committed is True
        assert principal is Principal.HUMAN_CLI
        self.calls.append("cancelled")
        self.status = self.returned_status
        return SimpleNamespace(status=self.returned_status)


class _RepoState:
    def __init__(self) -> None:
        self.operations: dict[str, ControlPlaneOperationRecord] = {}
        self.bindings: dict[str, SessionRunBindingRecord] = {}
        self.locks: dict[tuple[str, str, str, str], StoryExecutionLockRecord] = {}
        self.events: list[ExecutionEventRecord] = []
        self.commits: list[tuple[str, bool, int, int]] = []


def _repo(state: _RepoState) -> ControlPlaneRuntimeRepository:
    def _commit(
        record: ControlPlaneOperationRecord,
        *,
        binding_to_save: SessionRunBindingRecord | None,
        binding_to_delete: BindingDeleteScope | None,
        locks: tuple[StoryExecutionLockRecord, ...],
        events: tuple[ExecutionEventRecord, ...],
        ownership_status_target: OwnershipStatus | None = None,
    ) -> None:
        state.commits.append(
            (record.operation_kind, binding_to_delete is not None, len(locks), len(events))
        )
        state.operations[record.op_id] = record
        if binding_to_save is not None:
            state.bindings[binding_to_save.session_id] = binding_to_save
        if ownership_status_target is not None:
            assert ownership_status_target is OwnershipStatus.ENDED
        if binding_to_delete is not None:
            existing = state.bindings.get(binding_to_delete.session_id)
            if existing is not None and (
                existing.project_key,
                existing.story_id,
                existing.run_id,
            ) != (
                binding_to_delete.project_key,
                binding_to_delete.story_id,
                binding_to_delete.run_id,
            ):
                raise RuntimeError("binding collision")
            state.bindings.pop(binding_to_delete.session_id, None)
        for lock in locks:
            state.locks[(lock.project_key, lock.story_id, lock.run_id, lock.lock_type)] = (
                lock
            )
        state.events.extend(events)

    return ControlPlaneRuntimeRepository(
        load_operation=state.operations.get,
        commit_operation_with_side_effects=_commit,
        has_committed_story_exit_operation_for_run=lambda project_key, story_id, run_id: any(
            op.status == "committed"
            and op.operation_kind == "story_exit"
            and op.project_key == project_key
            and op.story_id == story_id
            and op.run_id == run_id
            for op in state.operations.values()
        ),
        load_binding=state.bindings.get,
        load_lock=lambda project_key, story_id, run_id, lock_type: state.locks.get(
            (project_key, story_id, run_id, lock_type)
        ),
    )


def _seed_binding(state: _RepoState) -> None:
    state.bindings["sess-1"] = SessionRunBindingRecord(
        session_id="sess-1",
        project_key="ak3",
        story_id="AG3-073",
        run_id="run-1",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-073",),
        binding_version="1",
        updated_at=NOW,
    )


def _valid_run_state(*, deltas: tuple[str, ...] = ()) -> ExitRunState:
    return ExitRunState(
        project_key="ak3",
        story_id="AG3-073",
        run_id="run-1",
        session_id="sess-1",
        human_design_required=True,
        remediation_exhausted=True,
        split_or_replan_available=False,
        reclassification_available=False,
        standard_contract_viable=False,
        architecture_blockers=("Integration choice requires human design.",),
        open_questions=("Which integration strategy should continue?",),
        recommendation="Human takeover.",
        out_of_contract_deltas=deltas,
    )


def _request(
    *,
    principal: Principal = Principal.HUMAN_CLI,
    exit_id: str = "exit-1",
) -> StoryExitRequest:
    return StoryExitRequest(
        project_key="ak3",
        story_id="AG3-073",
        run_id="run-1",
        session_id="sess-1",
        reason=ExitReason.SOLUTION_VIABILITY_REQUIRES_HUMAN_DESIGN,
        note="handoff",
        principal=principal,
        exit_id=exit_id,
    )


def _service(
    state: _RepoState,
    tmp_path: Path,
    *,
    story_service: _StoryService | None = None,
    governance: _Governance | None = None,
    run_state: ExitRunState | None = None,
) -> StoryExitService:
    return StoryExitService(
        control_plane_repository=_repo(state),
        story_service=story_service or _StoryService(),
        governance=governance or _Governance(),
        artifact_root=tmp_path,
        run_state_loader=lambda _request: run_state or _valid_run_state(),
        now_fn=lambda: NOW,
    )


def test_reason_enum_is_exact_and_unknown_reason_fails_closed() -> None:
    assert {reason.value for reason in ExitReason} == {
        "solution_viability_requires_human_design",
        "integration_strategy_not_scope_question",
        "integration_budget_exhausted",
        "approved_manifest_no_longer_sufficient",
        "bound_story_contract_no_longer_fit_for_decision_space",
    }
    with pytest.raises(ValueError):
        ExitReason("normal_difficulty")


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("normal_difficulty_excluded", "normal_difficulty_excluded"),
        ("mere_agent_uncertainty_excluded", "mere_agent_uncertainty_excluded"),
        ("usual_remediation_excluded", "usual_remediation_excluded"),
        ("split_or_replan_excluded", "split_or_replan_excluded"),
    ],
)
def test_admissibility_assessment_blocks_each_typed_prohibition(
    field: str,
    message: str,
) -> None:
    values = {
        "normal_difficulty_excluded": True,
        "mere_agent_uncertainty_excluded": True,
        "usual_remediation_excluded": True,
        "split_or_replan_excluded": True,
    }
    values[field] = False
    assessment = AdmissibilityAssessment(**values)
    review = AlternativeReview(
        standard_contract_checked=True,
        standard_contract_rejection_reason="not viable",
        reclassification_checked=True,
        reclassification_rejection_reason="not viable",
        split_checked=True,
        split_rejection_reason="not viable",
    )
    record = _record(assessment=assessment, review=review)

    with pytest.raises(StoryExitError, match=message):
        StoryExitService(
            control_plane_repository=_repo(_RepoState()),
            story_service=_StoryService(),
            governance=_Governance(),
        ).exit_gate(record=record, dossier="filled")


def test_filled_alternative_review_string_does_not_bypass_admissibility() -> None:
    assessment = AdmissibilityAssessment(
        normal_difficulty_excluded=False,
        mere_agent_uncertainty_excluded=True,
        usual_remediation_excluded=True,
        split_or_replan_excluded=True,
    )
    review = AlternativeReview(
        standard_contract_checked=True,
        standard_contract_rejection_reason="Agent was uncertain but string is filled.",
        reclassification_checked=True,
        reclassification_rejection_reason="filled",
        split_checked=True,
        split_rejection_reason="filled",
    )

    with pytest.raises(StoryExitError, match="normal_difficulty_excluded"):
        StoryExitService(
            control_plane_repository=_repo(_RepoState()),
            story_service=_StoryService(),
            governance=_Governance(),
        ).exit_gate(record=_record(assessment=assessment, review=review), dossier="filled")


@pytest.mark.parametrize(
    ("field", "value", "blocked"),
    [
        ("standard_contract_checked", False, "standard_contract_checked"),
        ("standard_contract_rejection_reason", "", "standard_contract_rejection_reason"),
        ("reclassification_checked", False, "reclassification_checked"),
        ("reclassification_rejection_reason", "", "reclassification_rejection_reason"),
        ("split_checked", False, "split_checked"),
        ("split_rejection_reason", "", "split_rejection_reason"),
    ],
)
def test_alternative_review_blocks_missing_checks_and_empty_reasons(
    field: str,
    value: object,
    blocked: str,
) -> None:
    values: dict[str, object] = {
        "standard_contract_checked": True,
        "standard_contract_rejection_reason": "not viable",
        "reclassification_checked": True,
        "reclassification_rejection_reason": "not viable",
        "split_checked": True,
        "split_rejection_reason": "not viable",
    }
    values[field] = value
    review = AlternativeReview(**values)
    record = _record(review=review)

    with pytest.raises(StoryExitError, match=blocked):
        StoryExitService(
            control_plane_repository=_repo(_RepoState()),
            story_service=_StoryService(),
            governance=_Governance(),
        ).exit_gate(record=record, dossier="filled")


def test_exit_gate_requires_record_and_dossier_without_mutation() -> None:
    state = _RepoState()
    service = StoryExitService(
        control_plane_repository=_repo(state),
        story_service=_StoryService(),
        governance=_Governance(),
    )

    with pytest.raises(StoryExitError, match="record"):
        service.exit_gate(record=None, dossier="filled")
    with pytest.raises(StoryExitError, match="dossier"):
        service.exit_gate(record=_record(), dossier="")

    assert state.operations == {}
    assert state.commits == []


def test_story_exit_canonical_order_and_no_closure_operation(tmp_path: Path) -> None:
    state = _RepoState()
    _seed_binding(state)
    story_service = _StoryService()
    result = _service(state, tmp_path, story_service=story_service).exit_story(_request())

    assert result.operating_mode == "binding_invalid"
    assert story_service.calls == ["cancelled"]
    assert state.commits == [
        ("story_exit", False, 0, 0),
        ("story_exit", False, 2, 3),
    ]
    assert state.bindings["sess-1"].status == "revoked"
    assert state.bindings["sess-1"].revocation_reason == "story_ended"
    assert state.operations["exit-1"].operation_kind == "story_exit"
    assert all(op.operation_kind != "closure_complete" for op in state.operations.values())


def test_crash_after_fence_before_cancel_leaves_binding_and_resume_finishes(
    tmp_path: Path,
) -> None:
    state = _RepoState()
    _seed_binding(state)
    crashing_story_service = _StoryService(fail_before_cancel=True)
    service = _service(state, tmp_path, story_service=crashing_story_service)

    with pytest.raises(RuntimeError, match="crash"):
        service.exit_story(_request())

    assert state.commits == [("story_exit", False, 0, 0)]
    assert state.bindings["sess-1"].run_id == "run-1"
    assert _repo(state).has_committed_story_exit_operation_for_run(
        "ak3", "AG3-073", "run-1"
    )

    resumed_story_service = _StoryService()
    resumed = _service(state, tmp_path, story_service=resumed_story_service).exit_story(
        _request()
    )

    assert resumed.exit_finalized is True
    assert resumed_story_service.calls == ["cancelled"]
    assert state.commits == [
        ("story_exit", False, 0, 0),
        ("story_exit", False, 2, 3),
    ]
    assert state.bindings["sess-1"].status == "revoked"


def test_teardown_does_not_run_before_cancelled_status(tmp_path: Path) -> None:
    state = _RepoState()
    _seed_binding(state)
    story_service = _StoryService(returned_status="In Progress")

    with pytest.raises(StoryExitError, match="Cancelled"):
        _service(state, tmp_path, story_service=story_service).exit_story(_request())

    assert state.commits == [("story_exit", False, 0, 0)]
    assert state.bindings["sess-1"].run_id == "run-1"


def test_artifacts_have_producer_and_no_delta_file_without_deltas(tmp_path: Path) -> None:
    state = _RepoState()
    _seed_binding(state)

    result = _service(state, tmp_path).exit_story(_request())

    assert result.record.producer_id == "story_exit_service"
    assert result.manifest_snapshot.producer_id == "story_exit_service"
    assert (result.artifact_dir / "viability_dossier.md").exists()
    assert (result.artifact_dir / "story_exit_record.json").exists()
    assert (result.artifact_dir / "exit_manifest_snapshot.json").exists()
    assert not (result.artifact_dir / "delta_quarantine.json").exists()


def test_delta_quarantine_written_only_for_out_of_contract_deltas(tmp_path: Path) -> None:
    state = _RepoState()
    _seed_binding(state)

    result = _service(
        state,
        tmp_path,
        run_state=_valid_run_state(deltas=("unexpected file change",)),
    ).exit_story(_request())

    assert (result.artifact_dir / "delta_quarantine.json").exists()


def test_exit_class_viability_handoff_only_under_cancelled() -> None:
    with pytest.raises(ValidationError, match="Input should be 'Cancelled'"):
        StoryExitRecord(
            exit_id="exit-1",
            project_key="ak3",
            story_id="AG3-073",
            run_id="run-1",
            session_id="sess-1",
            reason=ExitReason.SOLUTION_VIABILITY_REQUIRES_HUMAN_DESIGN,
            principal=Principal.HUMAN_CLI,
            terminal_state="Done",
            exit_class=ExitClass.VIABILITY_HANDOFF,
            admissibility_assessment=AdmissibilityAssessment(
                normal_difficulty_excluded=True,
                mere_agent_uncertainty_excluded=True,
                usual_remediation_excluded=True,
                split_or_replan_excluded=True,
            ),
            alternative_review=AlternativeReview(
                standard_contract_checked=True,
                standard_contract_rejection_reason="filled",
                reclassification_checked=True,
                reclassification_rejection_reason="filled",
                split_checked=True,
                split_rejection_reason="filled",
            ),
            created_at=NOW,
        )


@pytest.mark.parametrize("principal", [Principal.ORCHESTRATOR, Principal.WORKER])
def test_non_human_principals_are_rejected(
    principal: Principal,
    tmp_path: Path,
) -> None:
    state = _RepoState()
    _seed_binding(state)

    with pytest.raises(StoryExitError, match="HUMAN_CLI"):
        _service(state, tmp_path).exit_story(_request(principal=principal))

    assert state.commits == []
    assert state.bindings["sess-1"].run_id == "run-1"


def test_exit_finalized_fails_when_cleanup_or_mode_postcondition_missing(
    tmp_path: Path,
) -> None:
    state = _RepoState()
    _seed_binding(state)
    service = _service(state, tmp_path, governance=_Governance(restored=False))

    with pytest.raises(StoryExitError, match="guards"):
        service.exit_story(_request())


def _record(
    *,
    assessment: AdmissibilityAssessment | None = None,
    review: AlternativeReview | None = None,
) -> StoryExitRecord:
    return StoryExitRecord(
        exit_id="exit-1",
        project_key="ak3",
        story_id="AG3-073",
        run_id="run-1",
        session_id="sess-1",
        reason=ExitReason.SOLUTION_VIABILITY_REQUIRES_HUMAN_DESIGN,
        principal=Principal.HUMAN_CLI,
        terminal_state=TerminalState.CANCELLED,
        exit_class=ExitClass.VIABILITY_HANDOFF,
        admissibility_assessment=assessment
        or AdmissibilityAssessment(
            normal_difficulty_excluded=True,
            mere_agent_uncertainty_excluded=True,
            usual_remediation_excluded=True,
            split_or_replan_excluded=True,
        ),
        alternative_review=review
        or AlternativeReview(
            standard_contract_checked=True,
            standard_contract_rejection_reason="filled",
            reclassification_checked=True,
            reclassification_rejection_reason="filled",
            split_checked=True,
            split_rejection_reason="filled",
        ),
        created_at=NOW,
    )
