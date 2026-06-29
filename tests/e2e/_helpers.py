"""Shared seeding helpers for E2E tests.

These helpers persist real story-lifecycle entities through the actual
``StateBackendStoryRepository`` so that the Setup-Phase preflight gate
(``governance/setup_preflight_gate/preflight.py``) sees an APPROVED Story
with the exact ``story_display_id`` the test drives the pipeline with.

No mocks: the same repository / persistence path that ``StoryService``
uses internally is exercised here, so the seeded story is visible to the
preflight gate, ``begin_progress`` and ``complete_story``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from agentkit.backend.state_backend.store.story_repository import StateBackendStoryRepository
from agentkit.backend.story_context_manager.story_model import (
    Story,
    StoryStatus,
    WireStoryType,
)

# Stable namespace so re-runs UPSERT the same row (stories.story_uuid PK)
# instead of colliding on the UNIQUE(story_display_id) constraint.
_E2E_STORY_NAMESPACE = uuid5(NAMESPACE_URL, "agentkit3-e2e-seed")


def seed_approved_story(
    *,
    project_key: str,
    story_display_id: str,
    story_number: int,
    story_type: WireStoryType,
    title: str,
    status: StoryStatus = StoryStatus.APPROVED,
) -> Story:
    """Persist a Story so the Setup preflight gate passes.

    The story is written via the real ``StateBackendStoryRepository``
    (UPSERT keyed on a deterministic ``story_uuid`` derived from
    ``story_display_id``), which is the same persistence the
    ``StoryService`` used by the preflight gate reads from. The story has
    no dependencies, so the ``dependencies_closed`` check passes.

    Args:
        project_key: Owning project key (must match the StoryContext seed).
        story_display_id: Exact display ID the pipeline runs with, e.g.
            ``"E2E-165"`` or ``"TEST-001"``.
        story_number: Project-local story number (>= 1). Must be unique per
            project; AK3 owns the story identity, so this is a project-local
            number derived from the ``story_id``/Story-Service record, and is
            never an external issue identifier (AG3-120, FK-91 §91.2 rule 9).
        story_type: Wire-level story type matching the test's StoryType.
        title: Human-readable story title.
        status: Lifecycle status to seed. Defaults to ``APPROVED`` (the
            state Setup expects before ``begin_progress``). Use
            ``IN_PROGRESS`` for closure-only tests that call
            ``complete_story`` without running Setup.

    Returns:
        The persisted ``Story`` entity.
    """
    story = Story(
        story_uuid=uuid5(_E2E_STORY_NAMESPACE, story_display_id),
        project_key=project_key,
        story_number=story_number,
        story_display_id=story_display_id,
        title=title,
        story_type=story_type,
        status=status,
        participating_repos=["agentkit3-testbed"],
        created_at=datetime.now(UTC),
    )
    StateBackendStoryRepository().save(story)
    return story
