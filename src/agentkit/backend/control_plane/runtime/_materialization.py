"""Pure materialization plans for runtime mutations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.records import (
    SessionRunBindingRecord,
)
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.telemetry.events import EventType

from ._edge_bundles import _build_edge_bundle, _build_fast_edge_bundle, _next_binding_version
from ._models import _StartPhaseMaterialization
from ._operation_records import _lifecycle_event_record

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.backend.control_plane.models import (
        PhaseMutationRequest,
    )

logger = logging.getLogger(__name__)

def _plan_story_scoped_materialization(
    *,
    run_id: str,
    phase: str,
    request: PhaseMutationRequest,
    now: datetime,
    previous_binding_version: str | None,
    ownership_epoch: int,
) -> _StartPhaseMaterialization:
    """Build (NO writes) the full story-scoped binding + locks + events (#1).

    Pure record construction for a standard/exploration run: the records and the
    edge bundle are built but NOT persisted, so the claimed start_phase finalize can
    write them atomically under the ownership CAS (ERROR-1). The complete/fail
    commit (``_mutate_phase``) reuses this planner too, applying the records under
    the atomic collision-gated commit (ERROR-2).

    Args:
        previous_binding_version: The session's currently persisted
            ``binding_version`` (read at the persistence boundary by the caller),
            or ``None`` when the session has no binding yet. The next version is
            derived DB-monotone from it (``+ 1``), not from a wall clock.
        ownership_epoch: (AG3-142, SOLL-017 accountability) The
            ``ownership_epoch`` this commit applies under -- stamped onto the
            lifecycle events (business continuity of artifacts/attempts/QA
            stays keyed on ``run_id``; this is audit-only accountability).
    """
    binding_version = _next_binding_version(previous_binding_version)
    binding = SessionRunBindingRecord(
        session_id=request.session_id,
        project_key=request.project_key,
        story_id=request.story_id,
        run_id=run_id,
        principal_type=request.principal_type,
        worktree_roots=tuple(request.worktree_roots),
        binding_version=binding_version,
        updated_at=now,
    )
    lock = StoryExecutionLockRecord(
        project_key=request.project_key,
        story_id=request.story_id,
        run_id=run_id,
        lock_type="story_execution",
        status="ACTIVE",
        worktree_roots=tuple(request.worktree_roots),
        binding_version=binding_version,
        activated_at=now,
        updated_at=now,
    )
    qa_lock = StoryExecutionLockRecord(
        project_key=request.project_key,
        story_id=request.story_id,
        run_id=run_id,
        lock_type="qa_artifact_write",
        status="ACTIVE",
        worktree_roots=tuple(request.worktree_roots),
        binding_version=binding_version,
        activated_at=now,
        updated_at=now,
    )
    bundle = _build_edge_bundle(
        binding=binding,
        lock=lock,
        qa_lock=qa_lock,
        sync_class="mutation",
        now=now,
    )
    events = (
        _lifecycle_event_record(
            event_type=EventType.SESSION_RUN_BINDING_CREATED,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            source_component=request.source_component,
            payload={
                "session_id": request.session_id,
                "principal_type": request.principal_type,
                "worktree_roots": list(request.worktree_roots),
                "ownership_epoch": ownership_epoch,
            },
            now=now,
            phase=phase,
        ),
        _lifecycle_event_record(
            event_type=EventType.STORY_EXECUTION_REGIME_ACTIVATED,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            source_component=request.source_component,
            payload={
                "session_id": request.session_id,
                "ownership_epoch": ownership_epoch,
            },
            now=now,
            phase=phase,
        ),
    )
    return _StartPhaseMaterialization(
        bundle=bundle,
        binding=binding,
        locks=(lock, qa_lock),
        events=events,
    )


def _plan_fast_materialization(
    *,
    request: PhaseMutationRequest,
    now: datetime,
) -> _StartPhaseMaterialization:
    """Build (NO writes) the fast-story plan: bundle only, no side effects (#1).

    A fast story materializes NO session binding, NO ``story_execution`` lock and
    NO ``qa_artifact_write`` lock, so the plan carries an empty binding / locks /
    events but a valid ``ai_augmented`` bundle. The story-scoped guards never
    activate; the baseline guards (BranchGuard et al.) stay active in every mode.
    """
    bundle = _build_fast_edge_bundle(
        project_key=request.project_key,
        sync_class="mutation",
        now=now,
    )
    return _StartPhaseMaterialization(bundle=bundle, binding=None, locks=(), events=())
