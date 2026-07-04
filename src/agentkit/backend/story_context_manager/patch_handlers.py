"""PATCH field-application dispatch for the story_context_manager BC.

This is the cohesive ``update_story_fields`` field-application unit extracted
from :mod:`agentkit.backend.story_context_manager.service`. It owns the wire-field ->
``Story`` mutation handlers, their dispatch table (``_PATCH_HANDLERS``) and the
``_apply_updates`` driver, plus the ``_get_project_repos`` repo-allowlist reader
they share with ``create_story``.

It does not import from ``service`` (one-directional dependency); ``service``
consumes ``apply_updates`` / ``_get_project_repos`` from here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.story_context_manager.errors import (
    ForbiddenFieldError,
    StoryValidationError,
)
from agentkit.backend.story_context_manager.wire_adapter import (
    FORBIDDEN_PATCH_FIELDS,
    validate_repos_against_project,
    validate_repos_not_empty,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.project_management.entities import Project
    from agentkit.backend.story_context_manager.story_model import Story


def _get_project_repos(project: Project | None) -> list[str]:
    """Extract the list of allowed repos from a Project entity.

    Reads ``Project.configuration.repositories`` (AG3-020).  An empty
    return value means "no restriction" and callers treat it accordingly;
    in production it is always populated because ``ProjectConfiguration``
    requires at least one repository entry.

    Args:
        project: The Project entity, or ``None`` when the project lookup
            failed upstream.

    Returns:
        The list of configured repository identifiers, or ``[]``.
    """
    if project is None:
        return []
    return list(project.configuration.repositories)


def _apply_updates(
    story: Story,
    updates: dict[str, object],
    project: Project | None,
) -> Story:
    """Apply wire-level field updates to a Story.

    Dispatches each wire field name to its handler in ``_PATCH_HANDLERS``.
    Unknown fields are silently ignored per REST PATCH semantics; fields
    in ``FORBIDDEN_PATCH_FIELDS`` raise :class:`ForbiddenFieldError`.

    AG3-143 (FK-59 §59.9a) note: none of the ``StorySpecification`` content
    fields (``need``, ``solution``, ``acceptance``, ``definition_of_done``,
    ``concept_refs``, ``guardrail_refs``, ``external_sources``) has a handler
    in ``_PATCH_HANDLERS`` today -- naming one here is a silent no-op (the
    "unknown field" branch below), independent of any execution-regime state.
    ``StoryService._reject_if_spec_frozen`` still classifies and rejects these
    fields fail-closed during an active execution regime BEFORE this dispatch
    ever runs; that rejection is deliberately preemptive (protects a field
    that has no live write path yet) rather than proof that a write would
    otherwise have happened.

    Args:
        story: Current Story instance (mutated in place).
        updates: Wire field name -> new value.
        project: Project entity (used by the ``repos`` handler).

    Returns:
        The mutated Story.

    Raises:
        ``StoryValidationError`` for invalid field values.
        ``ForbiddenFieldError`` for forbidden fields.
    """
    for field_key, value in updates.items():
        if field_key == "op_id":
            continue  # transport-level field, not part of the story
        handler = _PATCH_HANDLERS.get(field_key)
        if handler is not None:
            handler(story, value, project)
            continue
        if field_key in FORBIDDEN_PATCH_FIELDS:
            raise ForbiddenFieldError(
                f"Field {field_key!r} is forbidden in updates",
                detail={"forbidden_field": field_key},
            )
        # Unknown field -- ignore silently per REST PATCH semantics.
    return story


# ---------------------------------------------------------------------------
# _apply_updates dispatch handlers
# ---------------------------------------------------------------------------


def _patch_title(story: Story, value: object, _project: Project | None) -> None:
    if not isinstance(value, str) or not value.strip():
        raise StoryValidationError(
            "title must be a non-empty string",
            detail={"field": "title"},
        )
    story.title = value


def _patch_epic(story: Story, value: object, _project: Project | None) -> None:
    story.epic = str(value) if value is not None else ""


def _patch_module(story: Story, value: object, _project: Project | None) -> None:
    story.module = str(value) if value is not None else ""


def _patch_type(story: Story, value: object, _project: Project | None) -> None:
    from agentkit.backend.story_context_manager.wire_adapter import parse_wire_story_type
    story.story_type = parse_wire_story_type(str(value))


def _patch_size(story: Story, value: object, _project: Project | None) -> None:
    from agentkit.backend.story_context_manager.wire_adapter import parse_wire_story_size
    story.size = parse_wire_story_size(str(value))


def _patch_mode(story: Story, value: object, _project: Project | None) -> None:
    from agentkit.backend.story_context_manager.wire_adapter import parse_wire_story_mode
    story.mode = parse_wire_story_mode(
        str(value) if value is not None else None
    )


def _patch_repos(story: Story, value: object, project: Project | None) -> None:
    if not isinstance(value, list):
        raise StoryValidationError(
            "repos must be a list", detail={"field": "repos"},
        )
    repos = [str(r) for r in value]
    validate_repos_not_empty(repos)
    allowed = _get_project_repos(project)
    if allowed:
        validate_repos_against_project(repos, allowed)
    story.participating_repos = repos


def _patch_change_impact(
    story: Story, value: object, _project: Project | None,
) -> None:
    from agentkit.backend.story_context_manager.wire_adapter import parse_wire_change_impact
    story.change_impact = parse_wire_change_impact(str(value))


def _patch_concept_quality(
    story: Story, value: object, _project: Project | None,
) -> None:
    from agentkit.backend.story_context_manager.wire_adapter import parse_wire_concept_quality
    story.concept_quality = parse_wire_concept_quality(str(value))


def _patch_owner(story: Story, value: object, _project: Project | None) -> None:
    story.owner = str(value) if value is not None else ""


def _patch_risk(story: Story, value: object, _project: Project | None) -> None:
    from agentkit.backend.story_context_manager.wire_adapter import parse_wire_risk_level
    story.risk = parse_wire_risk_level(str(value))


def _patch_blocker(story: Story, value: object, _project: Project | None) -> None:
    story.blocker = str(value) if value is not None else None


def _patch_labels(story: Story, value: object, _project: Project | None) -> None:
    if not isinstance(value, list):
        raise StoryValidationError(
            "labels must be a list", detail={"field": "labels"},
        )
    story.labels = [str(label) for label in value]


def _patch_wave(story: Story, value: object, _project: Project | None) -> None:
    if not isinstance(value, int):
        raise StoryValidationError(
            "wave must be an integer", detail={"field": "wave"},
        )
    story.wave = value


def _patch_critical_path(
    story: Story, value: object, _project: Project | None,
) -> None:
    story.critical_path = bool(value)


_PATCH_HANDLERS: dict[str, Callable[[Story, object, Project | None], None]] = {
    "title": _patch_title,
    "epic": _patch_epic,
    "module": _patch_module,
    "type": _patch_type,
    "size": _patch_size,
    "mode": _patch_mode,
    "repos": _patch_repos,
    "change_impact": _patch_change_impact,
    "concept_quality": _patch_concept_quality,
    "owner": _patch_owner,
    "risk": _patch_risk,
    "blocker": _patch_blocker,
    "labels": _patch_labels,
    "wave": _patch_wave,
    "critical_path": _patch_critical_path,
}
