"""Unit tests for story_context_manager wire_adapter.

Tests the field-name and value translations between wire format and
internal domain model (formal.frontend-contracts).
"""

from __future__ import annotations

import pytest

from agentkit.story_context_manager.errors import ForbiddenFieldError, StoryValidationError
from agentkit.story_context_manager.story_model import (
    ChangeImpact,
    ConceptQuality,
    RiskLevel,
    Story,
    StorySpecification,
    StoryStatus,
    WireStoryMode,
    WireStoryType,
)
from agentkit.story_context_manager.wire_adapter import (
    FORBIDDEN_PATCH_FIELDS,
    check_forbidden_fields,
    parse_wire_change_impact,
    parse_wire_concept_quality,
    parse_wire_risk_level,
    parse_wire_status,
    parse_wire_story_mode,
    parse_wire_story_size,
    parse_wire_story_type,
    story_spec_to_wire,
    story_to_wire_summary,
    validate_repos_against_project,
    validate_repos_not_empty,
)

# ---------------------------------------------------------------------------
# story_to_wire_summary
# ---------------------------------------------------------------------------


def _make_story(**kwargs: object) -> Story:
    defaults: dict[str, object] = {
        "project_key": "AK3",
        "story_number": 1,
        "story_display_id": "AK3-1",
        "title": "Test story",
        "story_type": WireStoryType.IMPLEMENTATION,
        "participating_repos": ["ak3"],
    }
    defaults.update(kwargs)
    return Story(**defaults)


def test_story_to_wire_summary_maps_display_id_to_story_id() -> None:
    story = _make_story()
    wire = story_to_wire_summary(story)
    assert wire["story_id"] == "AK3-1"


def test_story_to_wire_summary_maps_participating_repos_to_repos() -> None:
    story = _make_story(participating_repos=["ak3", "ak3-frontend"])
    wire = story_to_wire_summary(story)
    assert wire["repos"] == ["ak3", "ak3-frontend"]


def test_story_to_wire_summary_encodes_status_as_wire_string() -> None:
    story = _make_story(status=StoryStatus.IN_PROGRESS)
    wire = story_to_wire_summary(story)
    assert wire["status"] == "In Progress"


def test_story_to_wire_summary_encodes_architecture_impact() -> None:
    story = _make_story(change_impact=ChangeImpact.ARCHITECTURE_IMPACT)
    wire = story_to_wire_summary(story)
    assert wire["change_impact"] == "Architecture Impact"


def test_story_to_wire_summary_mode_none() -> None:
    story = _make_story(mode=None)
    wire = story_to_wire_summary(story)
    assert wire["mode"] is None


def test_story_to_wire_summary_mode_fast() -> None:
    story = _make_story(mode=WireStoryMode.FAST)
    wire = story_to_wire_summary(story)
    assert wire["mode"] == "fast"


def test_story_to_wire_summary_created_at_none() -> None:
    story = _make_story(created_at=None)
    wire = story_to_wire_summary(story)
    assert wire["created_at"] is None


def test_story_to_wire_summary_created_at_isoformat() -> None:
    from datetime import UTC, datetime

    created = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    story = _make_story(created_at=created)
    wire = story_to_wire_summary(story)
    assert wire["created_at"] == created.isoformat()


# ---------------------------------------------------------------------------
# story_spec_to_wire
# ---------------------------------------------------------------------------


def test_story_spec_to_wire_basic() -> None:
    spec = StorySpecification(
        need="Need text",
        solution="Solution text",
        acceptance=["AC-1", "AC-2"],
    )
    wire = story_spec_to_wire(spec)
    assert wire["need"] == "Need text"
    assert wire["solution"] == "Solution text"
    assert wire["acceptance"] == ["AC-1", "AC-2"]
    assert wire["definition_of_done"] is None
    assert wire["concept_refs"] is None


def test_story_spec_to_wire_with_optional_fields() -> None:
    spec = StorySpecification(
        need=None,
        solution=None,
        acceptance=[],
        definition_of_done=["DoD-1"],
        concept_refs=["FK-01"],
        guardrail_refs=["GR-1"],
        external_sources=["https://example.com"],
    )
    wire = story_spec_to_wire(spec)
    assert wire["definition_of_done"] == ["DoD-1"]
    assert wire["concept_refs"] == ["FK-01"]
    assert wire["guardrail_refs"] == ["GR-1"]
    assert wire["external_sources"] == ["https://example.com"]


# ---------------------------------------------------------------------------
# parse helpers
# ---------------------------------------------------------------------------


def test_parse_wire_status_valid() -> None:
    assert parse_wire_status("In Progress") == StoryStatus.IN_PROGRESS
    assert parse_wire_status("Backlog") == StoryStatus.BACKLOG
    assert parse_wire_status("Approved") == StoryStatus.APPROVED
    assert parse_wire_status("Done") == StoryStatus.DONE
    assert parse_wire_status("Cancelled") == StoryStatus.CANCELLED


def test_parse_wire_status_invalid_raises() -> None:
    with pytest.raises(StoryValidationError, match="Invalid status"):
        parse_wire_status("in_progress")


def test_parse_wire_story_type_valid() -> None:
    assert parse_wire_story_type("implementation") == WireStoryType.IMPLEMENTATION
    assert parse_wire_story_type("bugfix") == WireStoryType.BUGFIX
    assert parse_wire_story_type("concept") == WireStoryType.CONCEPT
    assert parse_wire_story_type("research") == WireStoryType.RESEARCH


def test_parse_wire_story_type_invalid_raises() -> None:
    with pytest.raises(StoryValidationError, match="Invalid story type"):
        parse_wire_story_type("bug_fix")


def test_parse_wire_story_size_valid() -> None:
    for size_val in ["XS", "S", "M", "L", "XL"]:
        result = parse_wire_story_size(size_val)
        assert result.value == size_val


def test_parse_wire_story_size_xxl_rejected() -> None:
    """XXL ist kein Konzept-Wert (DK-10 §10.4) und mit AG3-021 entfallen."""
    with pytest.raises(StoryValidationError, match="Invalid story size"):
        parse_wire_story_size("XXL")


def test_parse_wire_story_size_invalid_raises() -> None:
    with pytest.raises(StoryValidationError, match="Invalid story size"):
        parse_wire_story_size("MEDIUM")


def test_parse_wire_story_mode_none() -> None:
    assert parse_wire_story_mode(None) is None


def test_parse_wire_story_mode_valid() -> None:
    assert parse_wire_story_mode("standard") == WireStoryMode.STANDARD
    assert parse_wire_story_mode("fast") == WireStoryMode.FAST


def test_parse_wire_story_mode_invalid_raises() -> None:
    with pytest.raises(StoryValidationError, match="Invalid story mode"):
        parse_wire_story_mode("turbo")


def test_parse_wire_change_impact_space_value() -> None:
    result = parse_wire_change_impact("Architecture Impact")
    assert result == ChangeImpact.ARCHITECTURE_IMPACT


def test_parse_wire_change_impact_invalid_raises() -> None:
    with pytest.raises(StoryValidationError, match="Invalid change_impact"):
        parse_wire_change_impact("architectural")


def test_parse_wire_concept_quality_valid() -> None:
    assert parse_wire_concept_quality("High") == ConceptQuality.HIGH
    assert parse_wire_concept_quality("Medium") == ConceptQuality.MEDIUM
    assert parse_wire_concept_quality("Low") == ConceptQuality.LOW


def test_parse_wire_risk_level_valid() -> None:
    assert parse_wire_risk_level("low") == RiskLevel.LOW
    assert parse_wire_risk_level("medium") == RiskLevel.MEDIUM
    assert parse_wire_risk_level("high") == RiskLevel.HIGH


# ---------------------------------------------------------------------------
# Repo validation
# ---------------------------------------------------------------------------


def test_validate_repos_not_empty_passes() -> None:
    validate_repos_not_empty(["ak3"])  # no exception


def test_validate_repos_not_empty_raises_on_empty() -> None:
    with pytest.raises(StoryValidationError, match="repos must contain"):
        validate_repos_not_empty([])


def test_validate_repos_against_project_passes_when_all_allowed() -> None:
    validate_repos_against_project(["ak3", "frontend"], ["ak3", "frontend", "backend"])


def test_validate_repos_against_project_raises_on_unknown() -> None:
    with pytest.raises(StoryValidationError, match="Unknown repos"):
        validate_repos_against_project(["ak3", "unknown-repo"], ["ak3"])


def test_validate_repos_against_project_passes_when_no_restriction() -> None:
    validate_repos_against_project(["any-repo"], [])  # empty allowed = no restriction


# ---------------------------------------------------------------------------
# check_forbidden_fields
# ---------------------------------------------------------------------------


def test_check_forbidden_fields_raises_on_status() -> None:
    with pytest.raises(ForbiddenFieldError, match="status"):
        check_forbidden_fields({"status": "Approved", "title": "ok"})


def test_check_forbidden_fields_raises_on_created_at() -> None:
    with pytest.raises(ForbiddenFieldError):
        check_forbidden_fields({"created_at": "2026-01-01"})


def test_check_forbidden_fields_raises_on_completed_at() -> None:
    with pytest.raises(ForbiddenFieldError):
        check_forbidden_fields({"completed_at": "2026-01-01"})


def test_check_forbidden_fields_passes_on_allowed_fields() -> None:
    check_forbidden_fields({"title": "New title", "repos": ["ak3"]})  # no exception


def test_forbidden_patch_fields_contains_expected() -> None:
    assert "status" in FORBIDDEN_PATCH_FIELDS
    assert "created_at" in FORBIDDEN_PATCH_FIELDS
    assert "completed_at" in FORBIDDEN_PATCH_FIELDS
    assert "title" not in FORBIDDEN_PATCH_FIELDS
