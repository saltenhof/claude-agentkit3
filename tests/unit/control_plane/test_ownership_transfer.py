"""Pure ownership-transfer basis tests for the R5 server-truth contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from agentkit.backend.control_plane.ownership import (
    BindingStatus,
    OwnershipAcquisition,
    OwnershipStatus,
)
from agentkit.backend.control_plane.ownership_transfer import (
    OwnershipBasis,
    TakeoverConfirmFailure,
    TakeoverRepoChallenge,
    challenge_invalidated_by_transition,
    evaluate_disowned_session_takeover_barrier,
    evaluate_takeover_confirm,
    ownership_anchor_unchanged,
    ownership_basis_of_active,
    ownership_basis_of_challenge,
    ownership_basis_unchanged,
    requires_human_approval,
)
from agentkit.backend.control_plane.records import (
    RunOwnershipRecord,
    SessionRunBindingRecord,
    TakeoverChallengeRecord,
)
from agentkit.backend.core_types.freeze import ActiveFreezeState, FreezeKind

_NOW = datetime(2026, 7, 10, 10, 0, tzinfo=UTC)


def _active() -> RunOwnershipRecord:
    return RunOwnershipRecord(
        project_key="tenant-a",
        story_id="AG3-148",
        run_id="run-148",
        owner_session_id="sess-owner",
        ownership_epoch=3,
        status=OwnershipStatus.ACTIVE,
        acquired_via=OwnershipAcquisition.SETUP,
        acquired_at=_NOW,
        audit_ref="op-setup",
    )


def _binding() -> SessionRunBindingRecord:
    return SessionRunBindingRecord(
        session_id="sess-owner",
        project_key="tenant-a",
        story_id="AG3-148",
        run_id="run-148",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/AG3-148",),
        binding_version="7",
        updated_at=_NOW,
    )


def _challenge() -> TakeoverChallengeRecord:
    return TakeoverChallengeRecord(
        challenge_id="challenge-148",
        request_op_id="op-request",
        project_key="tenant-a",
        story_id="AG3-148",
        run_id="run-148",
        requesting_session_id="sess-requester",
        requesting_principal_type="human_cli",
        requesting_worktree_roots=("T:/worktrees/AG3-148-requester",),
        reason="owner unavailable",
        owner_session_id="sess-owner",
        ownership_epoch=3,
        binding_version="7",
        phase_status="implementation",
        issued_at=_NOW,
        expires_at=_NOW + timedelta(minutes=15),
        repos=(),
        open_operation_ids=(),
        takeover_history_refs=(),
    )


@pytest.mark.parametrize(
    ("active", "binding"),
    [
        (None, _binding()),
        (replace(_active(), status=OwnershipStatus.ENDED), _binding()),
        (_active(), None),
        (_active(), replace(_binding(), status=BindingStatus.REVOKED.value, revocation_reason="exit")),
        (_active(), replace(_binding(), session_id="sess-other")),
        (_active(), replace(_binding(), project_key="tenant-b")),
        (_active(), replace(_binding(), story_id="AG3-149")),
        (_active(), replace(_binding(), run_id="run-other")),
    ],
    ids=[
        "missing-ownership",
        "non-active-ownership",
        "missing-binding",
        "non-active-binding",
        "session-mismatch",
        "project-mismatch",
        "story-mismatch",
        "run-mismatch",
    ],
)
def test_ownership_basis_of_active_fails_closed_on_missing_or_scope_mismatch(
    active: RunOwnershipRecord | None,
    binding: SessionRunBindingRecord | None,
) -> None:
    assert ownership_basis_of_active(active, binding) is None


@pytest.mark.parametrize(
    "challenge_basis",
    [
        OwnershipBasis("sess-other", 3, "7"),
        OwnershipBasis("sess-owner", 4, "7"),
        OwnershipBasis("sess-owner", 3, "8"),
    ],
    ids=["owner-session-only", "ownership-epoch-only", "binding-version-only"],
)
def test_each_single_field_basis_drift_is_terminal_invalidation(
    challenge_basis: OwnershipBasis,
) -> None:
    active_basis = OwnershipBasis("sess-owner", 3, "7")

    decision = evaluate_takeover_confirm(
        active_basis=active_basis,
        challenge_basis=challenge_basis,
        now=_NOW,
        challenge_expires_at=_NOW + timedelta(minutes=15),
        approval_status=None,
        approval_required=False,
        repo_evidence=(
            TakeoverRepoChallenge(
                repo_id="api",
                takeover_base_sha="abc123",
                last_push_at=_NOW,
                push_lag_hint=None,
                base_quality="pushed",
            ),
        ),
        current_epoch_disowned_session_id=None,
        beneficiary_session_id="sess-beneficiary",
        requesting_principal_type="orchestrator",
        request_reason="take over stalled work",
        current_epoch_was_takeover=False,
    )

    assert decision.accepted is False
    assert decision.failure is TakeoverConfirmFailure.CHALLENGE_INVALIDATED


@pytest.mark.parametrize("kind", tuple(FreezeKind))
def test_takeover_confirm_rule_8_rejects_each_active_freeze_regardless_of_basis(
    kind: FreezeKind,
) -> None:
    decision = evaluate_takeover_confirm(
        active_basis=None,
        challenge_basis=OwnershipBasis("stale-owner", 99, "99"),
        now=_NOW,
        challenge_expires_at=None,
        approval_status=None,
        approval_required=False,
        repo_evidence=(),
        current_epoch_disowned_session_id=None,
        beneficiary_session_id="sess-beneficiary",
        requesting_principal_type="human_cli",
        request_reason="audited takeover",
        current_epoch_was_takeover=False,
        active_freezes=(ActiveFreezeState(kind, "hard stop", "3"),),
    )

    assert decision == (
        type(decision)(False, TakeoverConfirmFailure.STORY_NOT_TAKEOVER_ADMISSIBLE)
    )


def test_freeze_is_a_typed_terminal_challenge_invalidation_reason() -> None:
    assert (
        challenge_invalidated_by_transition("freeze")
        is TakeoverConfirmFailure.CHALLENGE_INVALIDATED
    )


def test_disowned_session_cannot_immediately_reclaim_without_privileged_reason() -> None:
    failure = evaluate_disowned_session_takeover_barrier(
        current_epoch_disowned_session_id="session-a",
        beneficiary_session_id="session-a",
        requesting_principal_type="orchestrator",
        request_reason="reclaim",
        current_epoch_was_takeover=True,
    )
    assert (
        failure
        is TakeoverConfirmFailure.DISOWNED_SESSION_CANNOT_IMMEDIATELY_RECLAIM
    )


def test_repeat_transfer_requires_privileged_principal_and_reason() -> None:
    assert evaluate_disowned_session_takeover_barrier(
        current_epoch_disowned_session_id="session-a",
        beneficiary_session_id="session-c",
        requesting_principal_type="orchestrator",
        request_reason="repeat",
        current_epoch_was_takeover=True,
    ) is TakeoverConfirmFailure.REPEAT_TRANSFER_REQUIRES_PRIVILEGED_PRINCIPAL_AND_REASON
    assert evaluate_disowned_session_takeover_barrier(
        current_epoch_disowned_session_id="session-a",
        beneficiary_session_id="session-c",
        requesting_principal_type="human_cli",
        request_reason="audited correction",
        current_epoch_was_takeover=True,
    ) is None


def test_no_session_identity_bypasses_human_approval() -> None:
    """R2-4/AC10-negative: foreign identities have no carve-out surface."""
    assert requires_human_approval("orchestrator")
    assert requires_human_approval("interactive_agent")
    assert not requires_human_approval("human_cli")


def test_full_basis_and_weaker_reissue_anchor_have_distinct_roles() -> None:
    active_basis = ownership_basis_of_active(_active(), _binding())
    challenge_basis = ownership_basis_of_challenge(_challenge())
    binding_only_drift = replace(challenge_basis, binding_version="8")

    assert ownership_basis_unchanged(active_basis, challenge_basis)
    assert not ownership_basis_unchanged(active_basis, binding_only_drift)
    assert ownership_anchor_unchanged(active_basis, binding_only_drift)
    assert not ownership_anchor_unchanged(
        active_basis,
        replace(challenge_basis, ownership_epoch=4),
    )
