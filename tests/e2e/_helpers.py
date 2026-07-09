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

from agentkit.backend.state_backend.config import (
    StateBackendKind,
    load_state_backend_config,
)
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


def seed_active_run_ownership(
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    owner_session_id: str = "e2e-owner-session",
    ownership_epoch: int = 1,
) -> None:
    """Seed the active ``RunOwnershipRecord`` a real setup start would mint (AG3-144).

    The e2e pipeline harnesses drive the pipeline engine directly
    (``run_pipeline`` / the phase handlers), bypassing the control-plane that,
    in a real run, atomically mints the story's active
    ``run_ownership_records`` row at setup start (AG3-142
    ``finalize_control_plane_start_phase_global``). AG3-144 extends the
    ownership-lease fence to the mutating projection writes
    (``qa_stage_results`` / ``decision_records`` / closure-report file), which
    now require that active record to exist (no-lease-no-write, FK-91 §91.1a
    Rule 15). This helper re-establishes exactly that predecessor state via the
    sanctioned AG3-137 single-writer surface (``insert_run_ownership_record_global``,
    the SAME surface the landed AG3-142 tests use) so the harness faithfully
    reflects a real control-plane-admitted run rather than fabricating a
    lease-free one. ``run_id`` MUST equal the run's flow-execution ``run_id``
    (the control-plane creates both with one shared run id).

    K5 Postgres-only: a no-op on a non-Postgres backend (the ownership tables
    are Postgres-only; the SQLite path receives no fence mirroring).
    """
    if load_state_backend_config().backend is not StateBackendKind.POSTGRES:
        return
    from agentkit.backend.control_plane.ownership import (
        OwnershipAcquisition,
        OwnershipStatus,
    )
    from agentkit.backend.control_plane.records import RunOwnershipRecord
    from agentkit.backend.state_backend.story_lifecycle_store import (
        insert_run_ownership_record_global,
        load_active_run_ownership_record_global,
    )

    if load_active_run_ownership_record_global(project_key, story_id) is not None:
        return
    insert_run_ownership_record_global(
        RunOwnershipRecord(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            owner_session_id=owner_session_id,
            ownership_epoch=ownership_epoch,
            status=OwnershipStatus.ACTIVE,
            acquired_via=OwnershipAcquisition.SETUP,
            acquired_at=datetime.now(UTC),
            audit_ref="audit:e2e-seed",
        )
    )
