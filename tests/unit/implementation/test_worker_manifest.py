"""Unit tests for WorkerManifest (FK-26 §26.8.2) and its BLOCKED validator."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.backend.core_types import BlockingCategory
from agentkit.backend.implementation.manifest import (
    AttemptedRemediation,
    WorkerManifest,
    WorkerManifestStatus,
)


def _now() -> datetime:
    return datetime(2026, 6, 7, tzinfo=UTC)


def test_completed_manifest_is_valid() -> None:
    """A COMPLETED manifest needs no blocker fields."""
    manifest = WorkerManifest(
        story_id="AG3-044",
        run_id="run-1",
        status=WorkerManifestStatus.COMPLETED,
        completed_at=_now(),
        commit_sha="abc123",
        files_changed=["src/x.py"],
        acceptance_criteria_status={"AC-1": "ADDRESSED"},
    )
    assert manifest.status is WorkerManifestStatus.COMPLETED
    assert manifest.blocking_category is None


def test_completed_with_issues_is_valid() -> None:
    """COMPLETED_WITH_ISSUES is a valid status without blocker fields."""
    manifest = WorkerManifest(
        story_id="AG3-044",
        run_id="run-1",
        status=WorkerManifestStatus.COMPLETED_WITH_ISSUES,
        completed_at=_now(),
    )
    assert manifest.status is WorkerManifestStatus.COMPLETED_WITH_ISSUES


def test_blocked_manifest_with_all_required_fields_is_valid() -> None:
    """A BLOCKED manifest with the three required fields validates."""
    manifest = WorkerManifest(
        story_id="AG3-044",
        run_id="run-1",
        status=WorkerManifestStatus.BLOCKED,
        completed_at=_now(),
        blocking_category=BlockingCategory.POLICY_CONFLICT,
        blocking_issue="pre_commit_hook_secret_detection",
        recommended_next_action="Extend the pre-commit hook with exceptions",
        attempted_remediations=[
            AttemptedRemediation(approach="rename token", result="new matches"),
        ],
    )
    assert manifest.status is WorkerManifestStatus.BLOCKED
    assert manifest.blocking_category is BlockingCategory.POLICY_CONFLICT


@pytest.mark.parametrize(
    "drop",
    ["blocking_category", "blocking_issue", "recommended_next_action"],
)
def test_blocked_manifest_missing_required_field_fails_closed(drop: str) -> None:
    """BLOCKED without any required blocker field is rejected (fail-closed)."""
    fields: dict[str, object] = {
        "story_id": "AG3-044",
        "run_id": "run-1",
        "status": WorkerManifestStatus.BLOCKED,
        "completed_at": _now(),
        "blocking_category": BlockingCategory.ENVIRONMENTAL,
        "blocking_issue": "missing tool",
        "recommended_next_action": "install tool",
    }
    fields[drop] = None
    with pytest.raises(ValidationError, match="BLOCKED worker-manifest requires"):
        WorkerManifest(**fields)  # type: ignore[arg-type]


def test_blocked_manifest_blank_string_field_fails_closed() -> None:
    """A whitespace-only required blocker field is treated as missing."""
    with pytest.raises(ValidationError, match="BLOCKED worker-manifest requires"):
        WorkerManifest(
            story_id="AG3-044",
            run_id="run-1",
            status=WorkerManifestStatus.BLOCKED,
            completed_at=_now(),
            blocking_category=BlockingCategory.FIXABLE_CODE,
            blocking_issue="   ",
            recommended_next_action="fix it",
        )


def test_manifest_rejects_unknown_field() -> None:
    """extra='forbid': an unknown key is rejected fail-closed."""
    with pytest.raises(ValidationError):
        WorkerManifest(
            story_id="AG3-044",
            run_id="run-1",
            status=WorkerManifestStatus.COMPLETED,
            completed_at=_now(),
            unexpected="x",  # type: ignore[call-arg]
        )


def test_three_status_values() -> None:
    """FK-26 §26.8.2 — exactly three worker-manifest status values."""
    assert {s.value for s in WorkerManifestStatus} == {
        "completed",
        "completed_with_issues",
        "blocked",
    }
