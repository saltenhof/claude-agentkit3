"""Wire <-> Internal adapter for story_context_manager.

Handles all field-name and value translations between the wire format
(formal.frontend-contracts.*) and the internal domain model.

Translations:
  - ``repos`` (Wire) <-> ``participating_repos`` (Internal, FK-21 language)
  - ``status="In Progress"`` <-> ``StoryStatus.IN_PROGRESS``
  - ``size`` wire values ("XS","S","M","L","XL") -> ``StorySize`` (AG3-021)
  - ``type`` wire values -> ``WireStoryType``
  - ``story_id`` (Wire: display_id) <-> ``story_display_id`` (Internal)

All translations are explicit and exhaustive; there is no generic
string-passthrough. Unknown values raise ``StoryValidationError``.
"""

from __future__ import annotations

from agentkit.core_types import StorySize
from agentkit.story_context_manager.errors import StoryValidationError
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

# ---------------------------------------------------------------------------
# Story -> Wire dict (serialization)
# ---------------------------------------------------------------------------


def story_to_wire_summary(story: Story) -> dict[str, object]:
    """Convert a Story to the wire ``story_summary`` payload.

    Maps ``participating_repos`` -> ``repos`` and
    ``story_display_id`` -> ``story_id``.
    All enum values are their exact wire strings.
    """
    return {
        "story_id": story.story_display_id,
        "project_key": story.project_key,
        "title": story.title,
        "type": story.story_type.value,
        "status": story.status.value,
        "size": story.size.value,
        "mode": story.mode.value if story.mode is not None else None,
        "epic": story.epic,
        "module": story.module,
        "repos": list(story.participating_repos),
        "change_impact": story.change_impact.value,
        "concept_quality": story.concept_quality.value,
        "owner": story.owner,
        "wave": story.wave,
        "critical_path": story.critical_path,
        "risk": story.risk.value,
        "blocker": story.blocker,
        "dependencies": list(story.dependencies),
        "labels": list(story.labels),
        "qa_rounds": story.qa_rounds,
        "qa_rounds_exploration": story.qa_rounds_exploration,
        "qa_rounds_implementation": story.qa_rounds_implementation,
        "processing_time": story.processing_time,
        "created_at": story.created_at.isoformat() if story.created_at else None,
        "completed_at": (
            story.completed_at.isoformat() if story.completed_at else None
        ),
    }


def story_spec_to_wire(spec: StorySpecification) -> dict[str, object]:
    """Convert a StorySpecification to the wire ``story_specification`` payload."""
    return {
        "need": spec.need,
        "solution": spec.solution,
        "acceptance": list(spec.acceptance),
        "definition_of_done": list(spec.definition_of_done)
        if spec.definition_of_done is not None
        else None,
        "concept_refs": list(spec.concept_refs)
        if spec.concept_refs is not None
        else None,
        "guardrail_refs": list(spec.guardrail_refs)
        if spec.guardrail_refs is not None
        else None,
        "external_sources": list(spec.external_sources)
        if spec.external_sources is not None
        else None,
    }


# ---------------------------------------------------------------------------
# Wire dict -> Internal field parsing (deserialization helpers)
# ---------------------------------------------------------------------------


def parse_wire_status(raw: str) -> StoryStatus:
    """Parse a wire status string into ``StoryStatus``.

    Args:
        raw: Wire status string, e.g. ``"In Progress"``.

    Returns:
        The corresponding ``StoryStatus`` enum member.

    Raises:
        ``StoryValidationError`` if the value is not a valid status.
    """
    try:
        return StoryStatus(raw)
    except ValueError:
        valid = [s.value for s in StoryStatus]
        raise StoryValidationError(
            f"Invalid status {raw!r}; valid values: {valid}",
            detail={"field": "status", "invalid_value": raw, "valid_values": valid},
        ) from None


def parse_wire_story_type(raw: str) -> WireStoryType:
    """Parse a wire type string into ``WireStoryType``."""
    try:
        return WireStoryType(raw)
    except ValueError:
        valid = [t.value for t in WireStoryType]
        raise StoryValidationError(
            f"Invalid story type {raw!r}; valid values: {valid}",
            detail={"field": "type", "invalid_value": raw, "valid_values": valid},
        ) from None


def parse_wire_story_size(raw: str) -> StorySize:
    """Parse a wire size string into ``StorySize`` (AG3-021)."""
    try:
        return StorySize(raw)
    except ValueError:
        valid = [s.value for s in StorySize]
        raise StoryValidationError(
            f"Invalid story size {raw!r}; valid values: {valid}",
            detail={"field": "size", "invalid_value": raw, "valid_values": valid},
        ) from None


def parse_wire_story_mode(raw: str | None) -> WireStoryMode | None:
    """Parse a wire mode string into ``WireStoryMode`` or None."""
    if raw is None:
        return None
    try:
        return WireStoryMode(raw)
    except ValueError:
        valid = [m.value for m in WireStoryMode]
        raise StoryValidationError(
            f"Invalid story mode {raw!r}; valid values: {valid}",
            detail={"field": "mode", "invalid_value": raw, "valid_values": valid},
        ) from None


def parse_wire_change_impact(raw: str) -> ChangeImpact:
    """Parse a wire change_impact string into ``ChangeImpact``."""
    try:
        return ChangeImpact(raw)
    except ValueError:
        valid = [c.value for c in ChangeImpact]
        raise StoryValidationError(
            f"Invalid change_impact {raw!r}; valid values: {valid}",
            detail={
                "field": "change_impact",
                "invalid_value": raw,
                "valid_values": valid,
            },
        ) from None


def parse_wire_concept_quality(raw: str) -> ConceptQuality:
    """Parse a wire concept_quality string into ``ConceptQuality``."""
    try:
        return ConceptQuality(raw)
    except ValueError:
        valid = [c.value for c in ConceptQuality]
        raise StoryValidationError(
            f"Invalid concept_quality {raw!r}; valid values: {valid}",
            detail={
                "field": "concept_quality",
                "invalid_value": raw,
                "valid_values": valid,
            },
        ) from None


def parse_wire_risk_level(raw: str) -> RiskLevel:
    """Parse a wire risk string into ``RiskLevel``."""
    try:
        return RiskLevel(raw)
    except ValueError:
        valid = [r.value for r in RiskLevel]
        raise StoryValidationError(
            f"Invalid risk {raw!r}; valid values: {valid}",
            detail={"field": "risk", "invalid_value": raw, "valid_values": valid},
        ) from None


def validate_repos_not_empty(repos: list[str]) -> None:
    """Raise StoryValidationError if repos list is empty."""
    if not repos:
        raise StoryValidationError(
            "repos must contain at least one entry",
            detail={"field": "repos", "constraint": "min_length_1"},
        )


def validate_repos_against_project(
    repos: list[str],
    allowed_repos: list[str],
) -> None:
    """Raise StoryValidationError if any repo is not in project config.

    Args:
        repos: repos list from the wire request.
        allowed_repos: ``Project.configuration.repositories[]`` or
            the list of registered repos for the project.

    Raises:
        ``StoryValidationError`` with ``detail.unknown_repos`` if any
        repo is not in the allowed set.
    """
    if not allowed_repos:
        # No repo restriction configured — allow any
        return
    unknown = [r for r in repos if r not in allowed_repos]
    if unknown:
        raise StoryValidationError(
            f"Unknown repos: {unknown}. "
            f"Allowed repos for this project: {allowed_repos}",
            detail={"unknown_repos": unknown, "allowed_repos": allowed_repos},
        )


# ---------------------------------------------------------------------------
# Forbidden-field check for PATCH / PUT /fields
# ---------------------------------------------------------------------------

FORBIDDEN_PATCH_FIELDS: frozenset[str] = frozenset(
    {"status", "created_at", "completed_at"}
)


def check_forbidden_fields(body: dict[str, object]) -> None:
    """Raise ForbiddenFieldError if any forbidden field is present.

    Args:
        body: Parsed request body dict.

    Raises:
        ``ForbiddenFieldError`` for the first forbidden field found.
    """
    from agentkit.story_context_manager.errors import ForbiddenFieldError

    found = FORBIDDEN_PATCH_FIELDS & body.keys()
    if found:
        field = next(iter(sorted(found)))
        raise ForbiddenFieldError(
            f"Field {field!r} is forbidden in PATCH requests; "
            "use the dedicated approve/reject/cancel endpoints for status changes",
            detail={"forbidden_field": field},
        )
