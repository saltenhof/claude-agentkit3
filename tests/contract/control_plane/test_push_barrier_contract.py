"""Contract pins for the AG3-147 push-barrier / merge-precondition A-core.

Guards the stability of the reusable SOLL-190 merge precondition (AC12, the
AG3-152 consumer) and the ARCH-55 English wire-code vocabulary (AC14): the
barrier block codes, the write-release refusal codes, the push-gate refusal
codes and the degradation finding code are stable, English, snake_case
identifiers that neighbouring stories and read models depend on.
"""

from __future__ import annotations

import pytest

from agentkit.backend.control_plane.push_sync import (
    REF_PROTECTION_DEGRADATION_CODE,
    MergePrecondition,
    PushBarrierBlockCode,
    PushGateRefusalCode,
    RepoPushVerificationInput,
    StoryRefWriteRefusalCode,
    SyncPointBarrierType,
    verify_pushed_across_repos,
)

pytestmark = pytest.mark.contract

_SYNC_POINT_ID = "phase_completion:op-1"


def _verified(repo_id: str, sha: str) -> RepoPushVerificationInput:
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
# AC12: the reusable merge precondition (SOLL-190) -- the AG3-152 consumer
# ---------------------------------------------------------------------------


def test_merge_precondition_shape_is_pinned() -> None:
    precondition = verify_pushed_across_repos([_verified("api", "a" * 40)])
    assert isinstance(precondition, MergePrecondition)
    # The consumer (AG3-152) depends on exactly these fields.
    assert precondition.satisfied is True
    assert precondition.blocking_repos == ()
    assert isinstance(precondition.detail, str)


def test_merge_precondition_blocks_when_any_repo_unverified() -> None:
    unverified = RepoPushVerificationInput(
        repo_id="web",
        edge_report_present=True,
        edge_reported_pushed=True,
        edge_reported_head_sha="a" * 40,
        server_ref_resolved=True,
        server_head_sha="b" * 40,  # server does not confirm the reported head
        edge_report_sync_point_id=_SYNC_POINT_ID,
        required_sync_point_id=_SYNC_POINT_ID,
    )
    precondition = verify_pushed_across_repos(
        [_verified("api", "a" * 40), unverified]
    )
    assert precondition.satisfied is False
    assert precondition.blocking_repos == ("web",)


# ---------------------------------------------------------------------------
# AC14 / ARCH-55: the wire-code vocabulary is stable, English, snake_case
# ---------------------------------------------------------------------------


def test_barrier_type_codes_are_pinned() -> None:
    assert {t.value for t in SyncPointBarrierType} == {
        "phase_completion",
        "qa_cycle_boundary",
        "yield_point",
        "closure_entry",
        "pre_merge",
    }


def test_barrier_block_codes_are_pinned() -> None:
    assert {c.value for c in PushBarrierBlockCode} == {
        "no_edge_push_report",
        "stale_edge_push_report",
        "missing_sync_point_correlation",
        "edge_reports_backlog",
        "missing_edge_head_sha",
        "server_ref_unresolved",
        "server_head_mismatch",
        "no_participating_repos",
    }


def test_write_refusal_codes_are_pinned() -> None:
    assert {c.value for c in StoryRefWriteRefusalCode} == {
        "no_active_ownership",
        "ownership_transferred",
        "stale_ownership_epoch",
    }


def test_push_gate_refusal_codes_are_pinned() -> None:
    assert {c.value for c in PushGateRefusalCode} == {
        "offline_no_server_confirmation",
        "ownership_not_confirmed",
        "non_official_ref",
    }


def test_degradation_code_is_pinned() -> None:
    assert REF_PROTECTION_DEGRADATION_CODE == "ref_protection_capability_unavailable"
