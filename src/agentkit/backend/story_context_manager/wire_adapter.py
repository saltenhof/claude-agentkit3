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

Also owns the Spec-Freeze field classification (AG3-143, FK-59 §59.9a):
whether a PATCH wire field is load-bearing (frozen during an active
execution regime) or administrative (always mutable). Blood-type A (pure,
technology-free classification; no I/O).
"""

from __future__ import annotations

from enum import StrEnum

from agentkit.backend.core_types import StorySize
from agentkit.backend.story_context_manager.errors import StoryValidationError
from agentkit.backend.story_context_manager.story_model import (
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
        "vectordb_conflict_resolved": story.vectordb_conflict_resolved,
        # AG3-072 (FK-54 §54.8.5): split lineage materialized on the source /
        # successors. ``split_from`` is the cancelled source on a successor;
        # ``split_successors`` is the real successor id set on the source.
        "split_from": story.split_from,
        "split_successors": list(story.split_successors),
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
    from agentkit.backend.story_context_manager.errors import ForbiddenFieldError

    found = FORBIDDEN_PATCH_FIELDS & body.keys()
    if found:
        field = next(iter(sorted(found)))
        raise ForbiddenFieldError(
            f"Field {field!r} is forbidden in PATCH requests; "
            "use the dedicated approve/reject/cancel endpoints for status changes",
            detail={"forbidden_field": field},
        )


# ---------------------------------------------------------------------------
# Spec-Freeze field classification (AG3-143, FK-59 §59.9a)
# ---------------------------------------------------------------------------


class StoryFieldSensitivity(StrEnum):
    """Whether a PATCH wire field is frozen during an active execution regime.

    FK-59 §59.9a: load-bearing story-spec fields (Scope, acceptance
    criteria, story text -- i.e. the ``StorySpecification`` content) are
    frozen while the story has an active execution regime; administrative
    metadata (labels, display name, and comparable non-axis fields per §59.9)
    stays free. Exactly two classes -- the concept draws no third "maybe".
    """

    LOAD_BEARING = "load_bearing"
    ADMINISTRATIVE = "administrative"


#: FK-59 §59.9a + §59.9: the CLOSED allowlist of wire fields explicitly named
#: as administrative / non-axis metadata: ``labels`` ("labels", §59.9a),
#: ``title`` ("display name", §59.9a -- the Story wire model's display name),
#: ``change_impact`` (explicitly listed non-axis, §59.9), ``module``
#: ("component assignment", §59.9), ``repos`` ("repo affinity", §59.9).
#: This is a typed ALLOWLIST, not a growing denylist (FIX THE MODEL): every
#: field NOT in this set -- including ``story_type`` (itself an explicit
#: persistent contract axis, §59.3.1/§59.4.1), every ``StorySpecification``
#: content field (``need``, ``solution``, ``acceptance``,
#: ``definition_of_done``, ``concept_refs``, ``guardrail_refs``,
#: ``external_sources``) and any unclassified/future field -- is
#: LOAD_BEARING by construction (fail-closed default, AC7). Forbidden fields
#: (``FORBIDDEN_PATCH_FIELDS``) are governed by their own absolute, regime-
#: independent prohibition and are never consulted here (see
#: ``contains_load_bearing_patch_field``).
_ADMINISTRATIVE_PATCH_FIELDS: frozenset[str] = frozenset(
    {"title", "labels", "change_impact", "module", "repos"}
)


def classify_story_patch_field(field_key: str) -> StoryFieldSensitivity:
    """Classify one wire field key per FK-59 §59.9a (fail-closed default).

    Args:
        field_key: The wire field name from a PATCH/PUT body.

    Returns:
        ``ADMINISTRATIVE`` iff *field_key* is in the closed allowlist;
        ``LOAD_BEARING`` for every other field (including unknown/future
        fields -- fail-closed, AC7).
    """
    if field_key in _ADMINISTRATIVE_PATCH_FIELDS:
        return StoryFieldSensitivity.ADMINISTRATIVE
    return StoryFieldSensitivity.LOAD_BEARING


def contains_load_bearing_patch_field(updates: dict[str, object]) -> bool:
    """Whether *updates* touches at least one load-bearing spec field.

    Two keys are exempt from classification entirely (never "load-bearing",
    never "administrative" -- simply not in scope of the Spec-Freeze
    question): ``op_id`` is a transport-level idempotency key, never story
    content (mirrors ``_apply_updates``'s own skip); and
    ``FORBIDDEN_PATCH_FIELDS`` (``status``/``created_at``/``completed_at``)
    are governed by their OWN absolute, regime-independent prohibition
    (``check_forbidden_fields``) -- applying Spec-Freeze semantics to an
    always-forbidden field would be meaningless and would needlessly widen
    the Postgres-only execution-regime read to PATCHes that can never
    succeed anyway.

    Args:
        updates: Wire field name -> new value (as passed to
            ``update_story_fields``).

    Returns:
        ``True`` iff at least one key classifies as ``LOAD_BEARING``.
    """
    return any(
        classify_story_patch_field(field_key) is StoryFieldSensitivity.LOAD_BEARING
        for field_key in updates
        if field_key != "op_id" and field_key not in FORBIDDEN_PATCH_FIELDS
    )
