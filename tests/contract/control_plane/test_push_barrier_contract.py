"""Contract pins for the AG3-147 push-barrier A-core.

Guards the stability of the ARCH-55 English wire-code vocabulary (AC14): the
barrier type codes, barrier block codes, write-release refusal codes, push-gate
refusal codes and degradation finding code are stable, English, snake_case
identifiers that neighbouring stories and read models depend on.
"""

from __future__ import annotations

import pytest

from agentkit.backend.control_plane.push_sync import (
    REF_PROTECTION_DEGRADATION_CODE,
    PushBarrierBlockCode,
    PushGateRefusalCode,
    StoryRefWriteRefusalCode,
    SyncPointBarrierType,
)

pytestmark = pytest.mark.contract


def test_barrier_type_codes_are_pinned() -> None:
    assert {t.value for t in SyncPointBarrierType} == {
        "phase_completion",
        "qa_cycle_boundary",
        "yield_point",
        "closure_entry",
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
