"""Unit tests for the sync-point / push-barrier A-core (AG3-147, push_sync.py).

Pure Blood-type A: no DB, no wire, no subprocess. These prove the fachliche
barrier/gate/release/degradation/freshness logic that the R-layer wires into
the runtime, the HTTP read model and the Edge push gate.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane.push_sync import (
    REF_PROTECTION_DEGRADATION_CODE,
    BarrierVerdict,
    PushBarrierBlockCode,
    PushGateRefusalCode,
    RepoPushVerificationInput,
    StoryRefWriteRefusalCode,
    SyncPointBarrierType,
    assess_ref_protection_capability,
    authorize_story_ref_write,
    decide_push_gate,
    evaluate_push_barrier,
    evaluate_repo_push,
    is_official_story_ref,
    official_story_ref,
    project_push_freshness,
    verify_pushed_across_repos,
)

_SHA_A = "a" * 40
_SHA_B = "b" * 40
_SYNC_POINT_ID = "phase_completion:op-1"
_NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _verified_repo(repo_id: str = "repo-a", sha: str = _SHA_A) -> RepoPushVerificationInput:
    """A repo whose Edge report and server ref-read agree (verified-pushed)."""
    return RepoPushVerificationInput(
        repo_id=repo_id,
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=sha,
        server_ref_resolved=True,
        server_head_sha=sha,
        edge_report_sync_point_id=_SYNC_POINT_ID,
        required_sync_point_id=_SYNC_POINT_ID,
    )


# ---------------------------------------------------------------------------
# AC1: two-stage barrier, fail-closed -- both negative paths individually
# ---------------------------------------------------------------------------


def test_repo_push_verified_when_edge_and_server_agree() -> None:
    verdict = evaluate_repo_push(_verified_repo())
    assert verdict.verified is True
    assert verdict.block_code is None


def test_ac1a_server_read_does_not_confirm_edge_head_blocks() -> None:
    """Edge reports push success, but the server head SHA differs -> block."""
    inp = RepoPushVerificationInput(
        repo_id="repo-a",
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=_SHA_A,
        server_ref_resolved=True,
        server_head_sha=_SHA_B,
        edge_report_sync_point_id=_SYNC_POINT_ID,
        required_sync_point_id=_SYNC_POINT_ID,
    )
    verdict = evaluate_repo_push(inp)
    assert verdict.verified is False
    assert verdict.block_code is PushBarrierBlockCode.SERVER_HEAD_MISMATCH


def test_ac1a_server_ref_unresolved_blocks_despite_edge_push_claim() -> None:
    inp = RepoPushVerificationInput(
        repo_id="repo-a",
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=_SHA_A,
        server_ref_resolved=False,
        server_head_sha=None,
        edge_report_sync_point_id=_SYNC_POINT_ID,
        required_sync_point_id=_SYNC_POINT_ID,
    )
    verdict = evaluate_repo_push(inp)
    assert verdict.verified is False
    assert verdict.block_code is PushBarrierBlockCode.SERVER_REF_UNRESOLVED


def test_ac1b_no_edge_report_blocks_even_when_server_would_pass() -> None:
    """Server read would confirm, but there is no Edge report -> block."""
    inp = RepoPushVerificationInput(
        repo_id="repo-a",
        edge_report_present=False,
        edge_reported_pushed=False,
        edge_reported_head_sha=None,
        server_ref_resolved=True,
        server_head_sha=_SHA_A,
        edge_report_sync_point_id=_SYNC_POINT_ID,
        required_sync_point_id=_SYNC_POINT_ID,
    )
    verdict = evaluate_repo_push(inp)
    assert verdict.verified is False
    assert verdict.block_code is PushBarrierBlockCode.NO_EDGE_PUSH_REPORT


def test_boundary_requires_correlated_edge_report_not_running_latest() -> None:
    """Regression: stale A==A evidence from an earlier sync-point must block."""
    inp = RepoPushVerificationInput(
        repo_id="repo-a",
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=_SHA_A,
        server_ref_resolved=True,
        server_head_sha=_SHA_A,
        edge_report_sync_point_id="phase_completion:op-old",
        required_sync_point_id="phase_completion:op-new",
    )
    verdict = evaluate_repo_push(inp)
    assert verdict.verified is False
    assert verdict.block_code is PushBarrierBlockCode.STALE_EDGE_PUSH_REPORT


def test_boundary_fails_closed_without_required_sync_point() -> None:
    """Regression: None correlation must not fall back to running-latest."""
    inp = RepoPushVerificationInput(
        repo_id="repo-a",
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=_SHA_A,
        server_ref_resolved=True,
        server_head_sha=_SHA_A,
        edge_report_sync_point_id=_SYNC_POINT_ID,
        required_sync_point_id=None,
    )
    verdict = evaluate_repo_push(inp)
    assert verdict.verified is False
    assert verdict.block_code is PushBarrierBlockCode.MISSING_SYNC_POINT_CORRELATION


def test_boundary_fails_closed_without_edge_sync_point() -> None:
    """Regression: untagged freshness must not satisfy a hard barrier."""
    inp = RepoPushVerificationInput(
        repo_id="repo-a",
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=_SHA_A,
        server_ref_resolved=True,
        server_head_sha=_SHA_A,
        edge_report_sync_point_id=None,
        required_sync_point_id=_SYNC_POINT_ID,
    )
    verdict = evaluate_repo_push(inp)
    assert verdict.verified is False
    assert verdict.block_code is PushBarrierBlockCode.MISSING_SYNC_POINT_CORRELATION


def test_qa_cycle_second_boundary_rejects_first_boundary_freshness() -> None:
    """Regression: two QA boundaries must not share one running-latest report."""
    first_qa_boundary = "qa_cycle_boundary:a1b2c3d4e5f6:round-1"
    second_qa_boundary = "qa_cycle_boundary:f6e5d4c3b2a1:round-2"
    stale = RepoPushVerificationInput(
        repo_id="repo-a",
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=_SHA_A,
        server_ref_resolved=True,
        server_head_sha=_SHA_A,
        edge_report_sync_point_id=first_qa_boundary,
        required_sync_point_id=second_qa_boundary,
    )

    stale_verdict = evaluate_push_barrier(
        SyncPointBarrierType.QA_CYCLE_BOUNDARY, [stale]
    )

    assert stale_verdict.passed is False
    assert stale_verdict.repo_verdicts[0].block_code is (
        PushBarrierBlockCode.STALE_EDGE_PUSH_REPORT
    )

    fresh = RepoPushVerificationInput(
        repo_id="repo-a",
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=_SHA_B,
        server_ref_resolved=True,
        server_head_sha=_SHA_B,
        edge_report_sync_point_id=second_qa_boundary,
        required_sync_point_id=second_qa_boundary,
    )
    fresh_verdict = evaluate_push_barrier(
        SyncPointBarrierType.QA_CYCLE_BOUNDARY, [fresh]
    )
    assert fresh_verdict.passed is True


def test_edge_reports_backlog_blocks() -> None:
    inp = RepoPushVerificationInput(
        repo_id="repo-a",
        edge_report_present=True,
        edge_reported_pushed=False,
        edge_reported_head_sha=_SHA_A,
        server_ref_resolved=True,
        server_head_sha=_SHA_A,
        edge_report_sync_point_id=_SYNC_POINT_ID,
        required_sync_point_id=_SYNC_POINT_ID,
    )
    verdict = evaluate_repo_push(inp)
    assert verdict.block_code is PushBarrierBlockCode.EDGE_REPORTS_BACKLOG


def test_missing_edge_head_sha_blocks() -> None:
    inp = RepoPushVerificationInput(
        repo_id="repo-a",
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=None,
        server_ref_resolved=True,
        server_head_sha=_SHA_A,
        edge_report_sync_point_id=_SYNC_POINT_ID,
        required_sync_point_id=_SYNC_POINT_ID,
    )
    verdict = evaluate_repo_push(inp)
    assert verdict.block_code is PushBarrierBlockCode.MISSING_EDGE_HEAD_SHA


# ---------------------------------------------------------------------------
# AC2: all four barrier types run through the same fail-closed engine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("barrier_type", list(SyncPointBarrierType))
def test_ac2_every_barrier_type_passes_when_verified(
    barrier_type: SyncPointBarrierType,
) -> None:
    verdict = evaluate_push_barrier(barrier_type, [_verified_repo()])
    assert isinstance(verdict, BarrierVerdict)
    assert verdict.passed is True
    assert verdict.barrier_type is barrier_type


@pytest.mark.parametrize("barrier_type", list(SyncPointBarrierType))
def test_ac2_every_barrier_type_blocks_without_edge_report(
    barrier_type: SyncPointBarrierType,
) -> None:
    inp = RepoPushVerificationInput(
        repo_id="repo-a",
        edge_report_present=False,
        edge_reported_pushed=False,
        edge_reported_head_sha=None,
        server_ref_resolved=True,
        server_head_sha=_SHA_A,
    )
    verdict = evaluate_push_barrier(barrier_type, [inp])
    assert verdict.passed is False
    assert verdict.blocking_repos == ("repo-a",)


def test_empty_repo_set_is_fail_closed() -> None:
    verdict = evaluate_push_barrier(SyncPointBarrierType.PHASE_COMPLETION, [])
    assert verdict.passed is False
    assert verdict.repo_verdicts[0].block_code is (
        PushBarrierBlockCode.NO_PARTICIPATING_REPOS
    )


# ---------------------------------------------------------------------------
# AC3: multi-repo -- one un-verified repo blocks even if all others pass
# ---------------------------------------------------------------------------


def test_ac3_one_unpushed_repo_blocks_the_barrier() -> None:
    good = _verified_repo("repo-a")
    bad = RepoPushVerificationInput(
        repo_id="repo-b",
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha=_SHA_A,
        server_ref_resolved=False,
        server_head_sha=None,
        edge_report_sync_point_id=_SYNC_POINT_ID,
        required_sync_point_id=_SYNC_POINT_ID,
    )
    verdict = evaluate_push_barrier(
        SyncPointBarrierType.CLOSURE_ENTRY, [good, bad]
    )
    assert verdict.passed is False
    assert verdict.blocking_repos == ("repo-b",)
    assert "repo-b" in verdict.blocking_summary()


def test_ac3_all_repos_verified_passes() -> None:
    verdict = evaluate_push_barrier(
        SyncPointBarrierType.CLOSURE_ENTRY,
        [_verified_repo("repo-a", _SHA_A), _verified_repo("repo-b", _SHA_B)],
    )
    assert verdict.passed is True
    assert verdict.blocking_repos == ()


# ---------------------------------------------------------------------------
# AC4/AC5: push-freshness projection -- backlog visible, no ownership effect
# ---------------------------------------------------------------------------


def test_ac4_pushed_outcome_clears_backlog_and_advances_sha() -> None:
    record = project_push_freshness(
        None,
        project_key="proj",
        story_id="AG3-147",
        run_id="run-1",
        repo_id="repo-a",
        reported_head_sha=_SHA_A,
        push_outcome="pushed",
        reported_at=_NOW,
        sync_point_id="phase_completion:op-1",
        command_id="run-1::sync_push::phase_completion:op-1::repo-a",
    )
    assert record.backlog is False
    assert record.last_pushed_head_sha == _SHA_A
    assert record.last_sync_point_id == "phase_completion:op-1"
    assert record.last_command_id == "run-1::sync_push::phase_completion:op-1::repo-a"
    assert record.backlog_detail is None


def test_ac4_behind_remote_raises_visible_backlog() -> None:
    record = project_push_freshness(
        None,
        project_key="proj",
        story_id="AG3-147",
        run_id="run-1",
        repo_id="repo-a",
        reported_head_sha=_SHA_A,
        push_outcome="behind_remote",
        reported_at=_NOW,
        sync_point_id="phase_completion:op-1",
        command_id="run-1::sync_push::phase_completion:op-1::repo-a",
    )
    assert record.backlog is True
    assert record.backlog_detail is not None
    assert record.last_pushed_head_sha is None


def test_ac4_backlog_preserves_prior_pushed_sha() -> None:
    first = project_push_freshness(
        None,
        project_key="proj",
        story_id="AG3-147",
        run_id="run-1",
        repo_id="repo-a",
        reported_head_sha=_SHA_A,
        push_outcome="pushed",
        reported_at=_NOW,
        sync_point_id="phase_completion:op-1",
        command_id="run-1::sync_push::phase_completion:op-1::repo-a",
    )
    later = project_push_freshness(
        first,
        project_key="proj",
        story_id="AG3-147",
        run_id="run-1",
        repo_id="repo-a",
        reported_head_sha=_SHA_B,
        push_outcome="behind_remote",
        reported_at=_NOW,
        sync_point_id="phase_completion:op-2",
        command_id="run-1::sync_push::phase_completion:op-2::repo-a",
    )
    assert later.backlog is True
    # The last KNOWN pushed head is preserved across a backlog report.
    assert later.last_pushed_head_sha == _SHA_A
    assert later.last_reported_head_sha == _SHA_B
    assert later.last_sync_point_id == "phase_completion:op-2"


# ---------------------------------------------------------------------------
# AC7/AC8: story/* write release only for the current (owner, epoch)
# ---------------------------------------------------------------------------


def test_ac7_active_owner_same_epoch_is_granted() -> None:
    auth = authorize_story_ref_write(
        active_owner_session_id="sess-1",
        active_ownership_epoch=3,
        requesting_session_id="sess-1",
        requesting_ownership_epoch=3,
    )
    assert auth.granted is True
    assert auth.refusal_code is None


def test_ac7_ex_owner_transferred_session_is_refused() -> None:
    auth = authorize_story_ref_write(
        active_owner_session_id="sess-2",
        active_ownership_epoch=4,
        requesting_session_id="sess-1",
        requesting_ownership_epoch=4,
    )
    assert auth.granted is False
    assert auth.refusal_code is StoryRefWriteRefusalCode.OWNERSHIP_TRANSFERRED


def test_ac7_stale_epoch_is_refused() -> None:
    auth = authorize_story_ref_write(
        active_owner_session_id="sess-1",
        active_ownership_epoch=5,
        requesting_session_id="sess-1",
        requesting_ownership_epoch=4,
    )
    assert auth.granted is False
    assert auth.refusal_code is StoryRefWriteRefusalCode.STALE_OWNERSHIP_EPOCH


def test_no_active_ownership_is_refused() -> None:
    auth = authorize_story_ref_write(
        active_owner_session_id=None,
        active_ownership_epoch=None,
        requesting_session_id="sess-1",
        requesting_ownership_epoch=1,
    )
    assert auth.granted is False
    assert auth.refusal_code is StoryRefWriteRefusalCode.NO_ACTIVE_OWNERSHIP


# ---------------------------------------------------------------------------
# AC9: ref-protection degradation WARNING
# ---------------------------------------------------------------------------


def test_ac9_capability_present_no_finding() -> None:
    assert (
        assess_ref_protection_capability(
            capability_supported=True, provider_label="github"
        )
        is None
    )


def test_ac9_capability_absent_yields_warning_finding() -> None:
    finding = assess_ref_protection_capability(
        capability_supported=False, provider_label="fake-provider"
    )
    assert finding is not None
    assert finding.severity == "warning"
    assert finding.finding_code == REF_PROTECTION_DEGRADATION_CODE
    assert finding.provider_label == "fake-provider"


# ---------------------------------------------------------------------------
# AC10: official ref only -- no WIP-ref push path
# ---------------------------------------------------------------------------


def test_ac10_official_ref_accepts_short_and_qualified() -> None:
    assert official_story_ref("AG3-147") == "story/AG3-147"
    assert is_official_story_ref("story/AG3-147", story_id="AG3-147")
    assert is_official_story_ref("refs/heads/story/AG3-147", story_id="AG3-147")


@pytest.mark.parametrize(
    "bad_ref",
    ["wip/AG3-147", "story/AG3-999", "main", "refs/heads/wip", "story/AG3-147-tmp"],
)
def test_ac10_non_official_refs_rejected(bad_ref: str) -> None:
    assert not is_official_story_ref(bad_ref, story_id="AG3-147")


# ---------------------------------------------------------------------------
# AC6/AC7: push gate -- online-required, bounded, no bundle fallback
# ---------------------------------------------------------------------------


def test_ac6_gate_open_when_online_and_owner_confirmed() -> None:
    decision = decide_push_gate(
        server_reachable=True,
        server_confirms_ownership=True,
        target_ref="story/AG3-147",
        story_id="AG3-147",
    )
    assert decision.allowed is True
    assert decision.refusal_code is None


def test_ac6_offline_refuses_push() -> None:
    decision = decide_push_gate(
        server_reachable=False,
        server_confirms_ownership=False,
        target_ref="story/AG3-147",
        story_id="AG3-147",
    )
    assert decision.allowed is False
    assert decision.refusal_code is PushGateRefusalCode.OFFLINE_NO_SERVER_CONFIRMATION


def test_ac7_gate_refuses_ex_owner_online() -> None:
    decision = decide_push_gate(
        server_reachable=True,
        server_confirms_ownership=False,
        target_ref="story/AG3-147",
        story_id="AG3-147",
    )
    assert decision.allowed is False
    assert decision.refusal_code is PushGateRefusalCode.OWNERSHIP_NOT_CONFIRMED


def test_ac10_gate_refuses_non_official_ref() -> None:
    decision = decide_push_gate(
        server_reachable=True,
        server_confirms_ownership=True,
        target_ref="wip/AG3-147",
        story_id="AG3-147",
    )
    assert decision.allowed is False
    assert decision.refusal_code is PushGateRefusalCode.NON_OFFICIAL_REF


# ---------------------------------------------------------------------------
# AC12: reusable merge precondition shares the barrier engine
# ---------------------------------------------------------------------------


def test_ac12_merge_precondition_satisfied_when_all_pushed() -> None:
    precondition = verify_pushed_across_repos(
        [_verified_repo("repo-a", _SHA_A), _verified_repo("repo-b", _SHA_B)]
    )
    assert precondition.satisfied is True
    assert precondition.blocking_repos == ()


def test_ac12_merge_precondition_blocks_on_unpushed_repo() -> None:
    bad = RepoPushVerificationInput(
        repo_id="repo-b",
        edge_report_present=False,
        edge_reported_pushed=False,
        edge_reported_head_sha=None,
        server_ref_resolved=False,
        server_head_sha=None,
    )
    precondition = verify_pushed_across_repos([_verified_repo("repo-a"), bad])
    assert precondition.satisfied is False
    assert precondition.blocking_repos == ("repo-b",)
