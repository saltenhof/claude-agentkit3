"""Server-head evidence adapter for persisted push-barrier verdicts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.backend.control_plane import push_barrier_lifecycle

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.push_verification import PushBarrierEvidencePort


def server_head_for_push_barrier_verdict(
    verdict: Any,
    *,
    evidence_factory: Callable[[], PushBarrierEvidencePort],
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    boundary_type: Any = None,
    boundary_id: str | None = None,
) -> str | None:
    """Read the current server head for one persisted push-barrier verdict."""

    resolved_boundary_type = boundary_type or verdict.boundary_type
    resolved_boundary_id = boundary_id or verdict.boundary_id
    inputs = evidence_factory().collect_repo_inputs(
        project_key=project_key or verdict.project_key,
        story_id=story_id or verdict.story_id,
        run_id=run_id or verdict.run_id,
        required_sync_point_id=push_barrier_lifecycle.boundary_sync_point_id(
            resolved_boundary_type,
            resolved_boundary_id,
            verdict.boundary_epoch,
        ),
    )
    for inp in inputs:
        if inp.repo_id == verdict.repo_id:
            return inp.server_head_sha if inp.server_ref_resolved else None
    return None
