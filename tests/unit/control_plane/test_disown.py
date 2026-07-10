"""Pure contract tests for the shared AG3-149 disown plan."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane.disown import build_disown_plan
from agentkit.backend.control_plane.ownership import (
    BindingRevocationReason,
    BindingStatus,
    OwnershipStatus,
)
from agentkit.backend.control_plane.records import SessionRunBindingRecord

NOW = datetime(2026, 7, 10, 12, tzinfo=UTC)


def _binding(*, status: str = BindingStatus.ACTIVE.value) -> SessionRunBindingRecord:
    return SessionRunBindingRecord(
        session_id="session-a",
        project_key="project-a",
        story_id="AG3-149",
        run_id="run-a",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/AG3-149",),
        binding_version="7",
        updated_at=datetime(2026, 7, 10, 11, tzinfo=UTC),
        status=status,
        revocation_reason=("story_reset" if status == BindingStatus.REVOKED.value else None),
    )


@pytest.mark.parametrize(
    ("reason", "status_target"),
    (
        (BindingRevocationReason.OWNERSHIP_TRANSFERRED, None),
        (BindingRevocationReason.STORY_ENDED, OwnershipStatus.ENDED),
        (BindingRevocationReason.STORY_RESET, OwnershipStatus.RESET),
        (BindingRevocationReason.STORY_SPLIT, OwnershipStatus.SPLIT),
    ),
)
def test_build_disown_plan_has_one_uniform_four_path_contract(
    reason: BindingRevocationReason,
    status_target: OwnershipStatus | None,
) -> None:
    plan = build_disown_plan(_binding(), reason, NOW)

    assert plan.reason is reason
    assert plan.revoked_binding.status == BindingStatus.REVOKED.value
    assert plan.revoked_binding.revocation_reason == reason.value
    assert plan.revoked_binding.updated_at == NOW
    assert plan.ownership_status_target is status_target
    assert plan.audit_payload == {
        "previous_owner_session_id": "session-a",
        "reason": reason.value,
    }
    assert plan.tombstone_worktree_roots == ("T:/worktrees/AG3-149",)
    assert plan.reconcile_operating_mode == "binding_invalid"
    assert plan.reconcile_reason == reason.value


def test_binding_revocation_reason_wire_vocabulary_is_exactly_four_keys() -> None:
    assert tuple(reason.value for reason in BindingRevocationReason) == (
        "ownership_transferred",
        "story_ended",
        "story_reset",
        "story_split",
    )


def test_build_disown_plan_rejects_already_revoked_binding() -> None:
    with pytest.raises(ValueError, match="requires an active"):
        build_disown_plan(
            _binding(status=BindingStatus.REVOKED.value),
            BindingRevocationReason.STORY_RESET,
            NOW,
        )
