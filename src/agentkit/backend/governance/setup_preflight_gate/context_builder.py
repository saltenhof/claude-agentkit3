"""Build StoryContext from the authoritative AK3 Story-Service record.

AK3 owns the user story itself (``StoryContext.story_id``, branch-safe via
``story/{story_id}``); GitHub is exclusively the code backend (FK-12 §12.1.1,
FK-91 §91.2 rule 9). The story context is therefore built purely from
``story_id`` plus the story attributes the AK3 Story-Service provides — never by
reading a GitHub issue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.governance.errors import StoryModeResolutionError
from agentkit.backend.governance.setup_preflight_gate.mode_determination import determine_mode
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import (
    ChangeImpact,
    ConceptQuality,
    WireStoryMode,
)
from agentkit.backend.story_context_manager.types import StoryType, get_profile

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.story_context_manager.service import StoryService


def build_story_context(
    project_root: Path,
    project_key: str,
    story_id: str,
    *,
    story_service: StoryService,
) -> StoryContext:
    """Build a ``StoryContext`` from the authoritative Story-Service record.

    AK3 is the single owner of the user story (``story_id``); GitHub is only
    the code backend (FK-12 §12.1.1, FK-91 §91.2 rule 9). The context is built
    from the AK3 Story-Service story-attributes record (story type, mode, title,
    size, labels, trigger inputs) — there is no GitHub issue read and no
    second, GitHub-derived story key.

    Fail-closed (CLAUDE.md FAIL-CLOSED): the authoritative ``story_service`` is
    mandatory — there is no service-less fabrication path. A wired service that
    does not know the story raises :class:`StoryModeResolutionError` rather than
    fabricating story attributes for an unresolvable identity. The story identity gate
    therefore rests entirely on the AK3 ``story_id`` (FK-22 §22.4 / FK-91 §91.2
    rule 9), never on a GitHub issue and never on a silent CONCEPT placeholder.

    Args:
        project_root: Path to the target project root.
        project_key: The owning project key.
        story_id: The story display identifier (the authoritative story key).
        story_service: The authoritative ``StoryService``. The story attributes are
            read from its record; an unresolvable identity fails closed.

    Returns:
        A ``StoryContext`` built from ``story_id`` and the Story-Service record.

    Raises:
        StoryModeResolutionError: When the story record is missing from the
            wired service (fail-closed identity gate).
    """
    detail = story_service.get_story_detail(story_id)
    if detail is None:
        raise StoryModeResolutionError(
            f"cannot build the story context: story {story_id!r} is not in the "
            "StoryService store (fail-closed -- setup must not fabricate "
            "story attributes for an unresolvable story identity; AK3 owns the story, "
            "FK-22 §22.4 / FK-91 §91.2 rule 9).",
            detail={"story_display_id": story_id},
        )
    story, spec = detail
    story_type = StoryType(story.story_type.value)
    story_mode = story.mode if story.mode is not None else WireStoryMode.STANDARD

    # Resolve trigger inputs from the authoritative Story record + spec (AC8).
    change_impact_val: ChangeImpact | None = story.change_impact
    concept_quality_val: ConceptQuality | None = story.concept_quality
    new_structures_val = story.new_structures
    # AG3-068 (FK-21 §21.12): project the authoritative VectorDB-conflict producer
    # flag so determine_mode reads the SSOT instead of the fail-closed default.
    vectordb_conflict_resolved_val = story.vectordb_conflict_resolved
    # AC8: project StorySpecification.concept_refs into the run context.
    # Fail-closed: empty tuple when spec absent or refs genuinely absent
    # (Trigger 1 fires for implementing stories without concept references).
    concept_refs_val: tuple[str, ...] = (
        tuple(ref for ref in spec.concept_refs if ref)
        if spec is not None and spec.concept_refs
        else ()
    )

    # AG3-057: build a preliminary shell to drive determine_mode, then build the
    # real context with the resolved execution route.
    _shell = StoryContext(
        project_key=project_key,
        story_number=_story_number_from_id(story_id) or story.story_number,
        story_id=story_id,
        story_type=story_type,
        execution_route=get_profile(story_type).default_mode,
        mode=story_mode,
        change_impact=change_impact_val,
        concept_quality=concept_quality_val,
        new_structures=new_structures_val,
        vectordb_conflict_resolved=vectordb_conflict_resolved_val,
        concept_refs=concept_refs_val,
        title=story.title,
        story_size=story.size,
        project_root=project_root,
        participating_repos=list(story.participating_repos),
        labels=list(story.labels),
        created_at=datetime.now(tz=UTC),
    )
    real_route = determine_mode(_shell, project_root=project_root)

    return StoryContext(
        project_key=project_key,
        story_number=_story_number_from_id(story_id) or story.story_number,
        story_id=story_id,
        story_type=story_type,
        execution_route=real_route,
        mode=story_mode,
        change_impact=change_impact_val,
        concept_quality=concept_quality_val,
        new_structures=new_structures_val,
        vectordb_conflict_resolved=vectordb_conflict_resolved_val,
        concept_refs=concept_refs_val,
        title=story.title,
        story_size=story.size,
        project_root=project_root,
        participating_repos=list(story.participating_repos),
        labels=list(story.labels),
        created_at=datetime.now(tz=UTC),
    )


def _story_number_from_id(story_id: str) -> int | None:
    suffix = story_id.rsplit("-", maxsplit=1)[-1]
    if not suffix.isdigit():
        return None
    return int(suffix)
