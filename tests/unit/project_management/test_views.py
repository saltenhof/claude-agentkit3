"""Unit tests for the project-management wire view models (AG3-040 sub-block a).

Pins the formal-spec contract (``formal.frontend-contracts.entities``):
frozen, extra-forbid, and exactly the normative fields.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.backend.project_management.views import (
    ProjectDetailView,
    ProjectModeLock,
    ProjectSummary,
    StoryCounters,
)


def _mode_lock() -> ProjectModeLock:
    return ProjectModeLock(project_key="tenant-a", mode="idle")


def _counters() -> StoryCounters:
    return StoryCounters(
        project_key="tenant-a",
        total=0,
        finished=0,
        running=0,
        ready=0,
        queue=0,
        blocked=0,
    )


def test_project_summary_normative_fields() -> None:
    summary = ProjectSummary(
        project_key="tenant-a",
        display_name="Tenant A",
        status="active",
    )
    assert summary.model_dump(mode="json") == {
        "project_key": "tenant-a",
        "display_name": "Tenant A",
        "status": "active",
    }


def test_project_summary_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        ProjectSummary.model_validate(
            {
                "project_key": "tenant-a",
                "display_name": "Tenant A",
                "status": "active",
                "story_id_prefix": "AG3",  # extra: forbidden
            },
        )


def test_project_summary_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        ProjectSummary(
            project_key="tenant-a",
            display_name="Tenant A",
            status="paused",  # type: ignore[arg-type]
        )


def test_project_summary_is_frozen() -> None:
    summary = ProjectSummary(
        project_key="tenant-a", display_name="Tenant A", status="active",
    )
    with pytest.raises(ValidationError):
        summary.status = "archived"  # type: ignore[misc]


def test_project_mode_lock_has_no_holder_count() -> None:
    lock = ProjectModeLock(project_key="tenant-a", mode="fast")
    assert lock.model_dump(mode="json") == {
        "project_key": "tenant-a",
        "mode": "fast",
    }
    with pytest.raises(ValidationError):
        ProjectModeLock.model_validate(
            {"project_key": "tenant-a", "mode": "fast", "holder_count": 1},
        )


def test_project_mode_lock_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        ProjectModeLock(project_key="tenant-a", mode="turbo")  # type: ignore[arg-type]


def test_story_counters_normative_fields() -> None:
    counters = StoryCounters(
        project_key="tenant-a",
        total=5,
        finished=1,
        running=2,
        ready=1,
        queue=1,
        blocked=0,
    )
    assert set(counters.model_dump().keys()) == {
        "project_key",
        "total",
        "finished",
        "running",
        "ready",
        "queue",
        "blocked",
    }


def test_story_counters_rejects_extra() -> None:
    with pytest.raises(ValidationError):
        StoryCounters.model_validate(
            {
                "project_key": "tenant-a",
                "total": 0,
                "finished": 0,
                "running": 0,
                "ready": 0,
                "queue": 0,
                "blocked": 0,
                "cancelled": 0,  # extra: forbidden
            },
        )


def test_project_detail_view_is_flat() -> None:
    view = ProjectDetailView(
        project_key="tenant-a",
        display_name="Tenant A",
        status="active",
        mode_lock=_mode_lock(),
        story_counters=_counters(),
        concept_anchors=[],
    )
    dumped = view.model_dump(mode="json")
    # Flat: project_key/display_name/status are direct, not nested under a
    # project_summary reference.
    assert dumped["project_key"] == "tenant-a"
    assert dumped["display_name"] == "Tenant A"
    assert dumped["status"] == "active"
    assert "project_summary" not in dumped
    assert set(dumped.keys()) == {
        "project_key",
        "display_name",
        "status",
        "mode_lock",
        "story_counters",
        "concept_anchors",
    }


def test_project_detail_view_rejects_extra() -> None:
    with pytest.raises(ValidationError):
        ProjectDetailView.model_validate(
            {
                "project_key": "tenant-a",
                "display_name": "Tenant A",
                "status": "active",
                "mode_lock": _mode_lock().model_dump(),
                "story_counters": _counters().model_dump(),
                "concept_anchors": [],
                "created_at": "2026-06-01T00:00:00Z",  # extra: forbidden
            },
        )


def test_project_detail_view_is_frozen() -> None:
    view = ProjectDetailView(
        project_key="tenant-a",
        display_name="Tenant A",
        status="active",
        mode_lock=_mode_lock(),
        story_counters=_counters(),
        concept_anchors=[],
    )
    with pytest.raises(ValidationError):
        view.display_name = "Other"  # type: ignore[misc]
