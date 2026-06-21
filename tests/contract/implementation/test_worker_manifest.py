"""Contract test: worker-manifest schema (FK-26 §26.8.2).

Pins the three status values and the BLOCKED required-field contract so a drift
in either fails immediately.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.backend.core_types import BlockingCategory
from agentkit.backend.implementation.manifest import (
    WorkerManifest,
    WorkerManifestStatus,
)

#: FK-26 §26.8.2 worker-manifest status wire values (exactly three).
_STATUS_WIRE = {
    "COMPLETED": "completed",
    "COMPLETED_WITH_ISSUES": "completed_with_issues",
    "BLOCKED": "blocked",
}

#: AG3-044 §2.1.4 BLOCKED required fields.
_BLOCKED_REQUIRED = ("blocking_category", "blocking_issue", "recommended_next_action")


def test_three_status_wire_values() -> None:
    """Exactly three status values with pinned wire strings (FK-26 §26.8.2)."""
    actual = {m.name: m.value for m in WorkerManifestStatus}
    assert actual == _STATUS_WIRE


def test_blocked_required_fields_enforced() -> None:
    """A BLOCKED manifest enforces all three required blocker fields."""
    base = {
        "story_id": "AG3-044",
        "run_id": "run-1",
        "status": WorkerManifestStatus.BLOCKED,
        "completed_at": datetime(2026, 6, 7, tzinfo=UTC),
        "blocking_category": BlockingCategory.POLICY_CONFLICT,
        "blocking_issue": "hook conflict",
        "recommended_next_action": "adjust hook",
    }
    # Complete BLOCKED manifest is valid.
    assert WorkerManifest(**base).status is WorkerManifestStatus.BLOCKED  # type: ignore[arg-type]
    # Dropping any required field is rejected.
    for field in _BLOCKED_REQUIRED:
        broken = dict(base)
        broken[field] = None
        with pytest.raises(ValidationError):
            WorkerManifest(**broken)  # type: ignore[arg-type]


def test_non_blocked_status_needs_no_blocker_fields() -> None:
    """COMPLETED / COMPLETED_WITH_ISSUES need no blocker fields."""
    for status in (
        WorkerManifestStatus.COMPLETED,
        WorkerManifestStatus.COMPLETED_WITH_ISSUES,
    ):
        manifest = WorkerManifest(
            story_id="AG3-044",
            run_id="run-1",
            status=status,
            completed_at=datetime(2026, 6, 7, tzinfo=UTC),
        )
        assert manifest.blocking_category is None
