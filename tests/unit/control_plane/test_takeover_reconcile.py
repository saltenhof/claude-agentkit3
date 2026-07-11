"""Pure AG3-151 takeover reconcile classifier tests."""

from __future__ import annotations

import pytest

from agentkit.backend.control_plane.takeover_reconcile import (
    TakeoverReconcileEvidence,
    classify_takeover_reconcile,
)

_BASE = "a" * 40


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({}, "identity_ok"),
        (
            {"remote_head_sha": "b" * 40},
            "remote_branch_diverged_after_takeover",
        ),
        (
            {"target_stale_or_dirty": True},
            "local_stale_or_dirty_takeover_target",
        ),
        ({"marker_present": False}, "contested_local_writes"),
    ],
)
def test_classify_takeover_reconcile_has_four_distinct_outcomes(
    updates: dict[str, object],
    expected: str,
) -> None:
    values: dict[str, object] = {
        "repo_id": "api",
        "takeover_base_sha": _BASE,
        "remote_head_sha": _BASE,
        "worktree_head_sha": _BASE,
        "marker_present": True,
        "reconcile_succeeded": True,
    }
    values.update(updates)
    result = classify_takeover_reconcile(TakeoverReconcileEvidence(**values))
    assert result.result_type == expected
    assert result.reconciled is (expected == "identity_ok")
