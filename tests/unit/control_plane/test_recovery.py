"""Pure recovery capability and supersede-decision tests."""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.backend.control_plane.ownership import (
    OwnershipAcquisition,
    OwnershipStatus,
)
from agentkit.backend.control_plane.records import RunOwnershipRecord
from agentkit.backend.control_plane.recovery import (
    RecoveryFailure,
    evaluate_recovery_admissibility,
    evaluate_recovery_capability,
)
from agentkit.backend.core_types.freeze import ActiveFreezeState, FreezeKind

NOW = datetime(2026, 7, 11, 10, tzinfo=UTC)


def _active(run_id: str = "run-old") -> RunOwnershipRecord:
    return RunOwnershipRecord(
        project_key="project-a",
        story_id="AG3-154",
        run_id=run_id,
        owner_session_id=f"session-{run_id}",
        ownership_epoch=1,
        status=OwnershipStatus.ACTIVE,
        acquired_via=OwnershipAcquisition.SETUP,
        acquired_at=NOW,
        audit_ref="op-setup",
    )


def _decision(
    records: tuple[RunOwnershipRecord, ...],
    *,
    run_id: str = "run-old",
    freezes: tuple[ActiveFreezeState, ...] = (),
    obligation: bool = False,
):
    return evaluate_recovery_admissibility(
        active_records=records,
        superseded_run_id=run_id,
        active_freezes=freezes,
        has_unreconciled_takeover=obligation,
    )


def test_recovery_supersede_decision_admits_exactly_one_active_record() -> None:
    active = _active()
    decision = _decision((active,))

    assert decision.admitted is True
    assert decision.superseded_record is active
    assert decision.failure is None


def test_recovery_hard_refuses_no_active_record() -> None:
    assert _decision(()).failure is RecoveryFailure.NOTHING_TO_RECOVER


def test_recovery_hard_refuses_multiple_active_records() -> None:
    assert _decision((_active(), _active("run-other"))).failure is (
        RecoveryFailure.MULTIPLE_ACTIVE_OWNERSHIP_RECORDS
    )


def test_recovery_hard_refuses_competing_active_run() -> None:
    assert _decision((_active("run-current"),)).failure is (
        RecoveryFailure.COMPETING_ACTIVE_OWNERSHIP
    )


def test_recovery_hard_refuses_blocking_freeze_with_distinct_code() -> None:
    freeze = ActiveFreezeState(
        kind=FreezeKind.CONFLICT_FREEZE,
        freeze_reason="conflicting operator decision",
        freeze_epoch="1",
    )
    assert _decision((_active(),), freezes=(freeze,)).failure is (
        RecoveryFailure.RECOVERY_BLOCKED_BY_FREEZE
    )


def test_recovery_hard_refuses_unreconciled_takeover_obligation() -> None:
    assert _decision((_active(),), obligation=True).failure is (
        RecoveryFailure.TAKEOVER_RECONCILE_REQUIRED
    )


def test_agent_recovery_is_refused_at_capability_layer() -> None:
    assert evaluate_recovery_capability(
        principal_type="interactive_agent",
        beneficiary_session_id="agent-session",
        reason="resume my crashed work",
        current_epoch_disowned_session_id="agent-session",
        current_epoch_was_takeover=True,
    ) is RecoveryFailure.RECOVERY_REQUIRES_HUMAN_CLI


def test_recovery_capability_requires_reason_and_reuses_ping_pong_barrier() -> None:
    assert evaluate_recovery_capability(
        principal_type="human_cli",
        beneficiary_session_id="human-session",
        reason=" ",
        current_epoch_disowned_session_id=None,
        current_epoch_was_takeover=False,
    ) is RecoveryFailure.RECOVERY_REASON_REQUIRED
    assert evaluate_recovery_capability(
        principal_type="human_cli",
        beneficiary_session_id="human-session",
        reason="operator inspected the orphaned claim",
        current_epoch_disowned_session_id="human-session",
        current_epoch_was_takeover=True,
    ) is None
