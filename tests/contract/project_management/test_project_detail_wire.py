"""Contract test: project_detail / mode_lock / story_counters wire shapes.

Pins the formal-spec contract exactly (AG3-040 sub-block a):
  - ``frontend-contracts.entity.project_detail`` is FLAT
    (``project_key``/``display_name``/``status`` direct, plus
    ``mode_lock``, ``story_counters``, ``concept_anchors``).
  - ``frontend-contracts.entity.project_mode_lock`` carries
    ``project_key`` + ``mode`` (NO ``holder_count``).
  - ``frontend-contracts.entity.story_counters`` carries
    ``project_key`` + the six int counters.
Drift in any field set fails this test.
"""

from __future__ import annotations

from agentkit.backend.project_management.views import (
    ProjectDetailView,
    ProjectModeLock,
    StoryCounters,
)

_DETAIL_FIELDS = frozenset(
    {
        "project_key",
        "display_name",
        "status",
        "mode_lock",
        "story_counters",
        "concept_anchors",
    },
)
_MODE_LOCK_FIELDS = frozenset({"project_key", "mode"})
_COUNTER_FIELDS = frozenset(
    {"project_key", "total", "finished", "running", "ready", "queue", "blocked"},
)


def test_project_detail_model_fields_are_exactly_the_contract() -> None:
    assert set(ProjectDetailView.model_fields.keys()) == _DETAIL_FIELDS


def test_project_detail_is_flat_not_nested_summary() -> None:
    # project_summary must NOT be a nested ref; the detail is flat.
    assert "project_summary" not in ProjectDetailView.model_fields


def test_project_mode_lock_fields_have_no_holder_count() -> None:
    fields = set(ProjectModeLock.model_fields.keys())
    assert fields == _MODE_LOCK_FIELDS
    assert "holder_count" not in fields


def test_story_counters_fields_are_exactly_the_contract() -> None:
    assert set(StoryCounters.model_fields.keys()) == _COUNTER_FIELDS


def test_project_detail_wire_dump_shape() -> None:
    view = ProjectDetailView(
        project_key="tenant-a",
        display_name="Tenant A",
        status="active",
        mode_lock=ProjectModeLock(project_key="tenant-a", mode="idle"),
        story_counters=StoryCounters(
            project_key="tenant-a",
            total=0,
            finished=0,
            running=0,
            ready=0,
            queue=0,
            blocked=0,
        ),
        concept_anchors=[],
    )
    dumped = view.model_dump(mode="json")
    assert set(dumped.keys()) == _DETAIL_FIELDS
    assert set(dumped["mode_lock"].keys()) == _MODE_LOCK_FIELDS
    assert set(dumped["story_counters"].keys()) == _COUNTER_FIELDS
