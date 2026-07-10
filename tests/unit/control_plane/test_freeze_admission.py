"""Pure freeze-family admission tests for AG3-150 pillars 1-3."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane.ownership import (
    OwnershipAcquisition,
    OwnershipStatus,
)
from agentkit.backend.control_plane.ownership_fence import (
    OwnershipRejectionReason,
    evaluate_ownership_admission,
)
from agentkit.backend.control_plane.records import RunOwnershipRecord
from agentkit.backend.core_types.freeze import (
    RESOLVING_COMMANDS_BY_KIND,
    ActiveFreezeState,
    FreezeKind,
)


def _active() -> RunOwnershipRecord:
    return RunOwnershipRecord(
        project_key="tenant-a",
        story_id="AG3-150",
        run_id="run-150",
        owner_session_id="session-owner",
        ownership_epoch=7,
        status=OwnershipStatus.ACTIVE,
        acquired_via=OwnershipAcquisition.SETUP,
        acquired_at=datetime(2026, 7, 11, tzinfo=UTC),
        audit_ref="op-setup",
    )


def _freeze(kind: FreezeKind) -> ActiveFreezeState:
    return ActiveFreezeState(
        kind=kind,
        freeze_reason="audited hard stop",
        freeze_epoch="11",
    )


@pytest.mark.parametrize("kind", tuple(FreezeKind))
def test_each_family_kind_blocks_unregistered_mutation_and_keeps_ownership_active(
    kind: FreezeKind,
) -> None:
    active = _active()
    admission = evaluate_ownership_admission(
        active_record=active,
        run_id=active.run_id,
        session_id=active.owner_session_id,
        active_freezes=(_freeze(kind),),
        command_id="phase_complete",
    )

    assert admission.admitted is False
    assert admission.rejection_reason is OwnershipRejectionReason.FREEZE_ACTIVE
    assert admission.active_record is active
    assert admission.active_record.status is OwnershipStatus.ACTIVE


@pytest.mark.parametrize("kind", tuple(FreezeKind))
def test_only_registry_resolving_command_passes_active_freeze(kind: FreezeKind) -> None:
    active = _active()
    command_id = next(iter(RESOLVING_COMMANDS_BY_KIND[kind]))

    admission = evaluate_ownership_admission(
        active_record=active,
        run_id=active.run_id,
        session_id=active.owner_session_id,
        active_freezes=(_freeze(kind),),
        command_id=command_id,
    )

    assert admission.admitted is True
    assert admission.rejection_reason is None


@pytest.mark.parametrize(
    "freeze",
    [
        ActiveFreezeState(None, "reason", "1"),
        ActiveFreezeState(FreezeKind.CONFLICT_FREEZE, None, "1"),
        ActiveFreezeState.unreadable(),
    ],
    ids=["unknown-kind", "missing-freeze-reason", "unreadable-state"],
)
def test_inconsistent_freeze_state_fails_closed(freeze: ActiveFreezeState) -> None:
    active = _active()
    admission = evaluate_ownership_admission(
        active_record=active,
        run_id=active.run_id,
        session_id=active.owner_session_id,
        active_freezes=(freeze,),
        command_id="resolve_conflict_freeze",
    )

    assert admission.admitted is False
    assert admission.rejection_reason is OwnershipRejectionReason.FREEZE_ACTIVE
