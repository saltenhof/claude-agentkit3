"""Repository surface for control-plane runtime lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.state_backend.store import (
    append_execution_event_global,
    delete_session_run_binding_global,
    load_control_plane_operation_global,
    load_session_run_binding_global,
    load_story_execution_lock_global,
    save_control_plane_operation_global,
    save_session_run_binding_global,
    save_story_execution_lock_global,
)
from agentkit.story.repository import StoryRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.control_plane.records import (
        ControlPlaneOperationRecord,
        SessionRunBindingRecord,
    )
    from agentkit.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.telemetry.contract.records import ExecutionEventRecord


def _load_story_context_via_story_surface(
    project_key: str,
    story_id: str,
) -> StoryContext | None:
    """Resolve a StoryContext through the sanctioned story read surface.

    Architecture Conformance AC004 (``architecture-conformance.rule.
    story_read_surface``): the global story read loader
    (``load_story_context_global``) may only be imported from
    ``agentkit.state_backend`` / ``agentkit.story.repository``. The control
    plane therefore consumes it via :class:`agentkit.story.repository.
    StoryRepository`, never by importing the loader symbol directly.
    """
    return StoryRepository().load_story_context(project_key, story_id)


@dataclass(frozen=True)
class ControlPlaneRuntimeRepository:
    """Persistence dependencies for runtime mutations and sync."""

    load_operation: Callable[[str], ControlPlaneOperationRecord | None] = (
        load_control_plane_operation_global
    )
    save_operation: Callable[[ControlPlaneOperationRecord], None] = (
        save_control_plane_operation_global
    )
    load_binding: Callable[[str], SessionRunBindingRecord | None] = (
        load_session_run_binding_global
    )
    save_binding: Callable[[SessionRunBindingRecord], None] = (
        save_session_run_binding_global
    )
    delete_binding: Callable[[str], None] = delete_session_run_binding_global
    load_lock: Callable[[str, str, str, str], StoryExecutionLockRecord | None] = (
        load_story_execution_lock_global
    )
    save_lock: Callable[[StoryExecutionLockRecord], None] = (
        save_story_execution_lock_global
    )
    append_event: Callable[[ExecutionEventRecord], None] = append_execution_event_global
    #: Authoritative server-side resolver for the run ``StoryContext`` keyed by
    #: ``(project_key, story_id)``. AG3-018 (FK-24 §24.3.4): the control plane
    #: reads the operating mode from the state-backend record, NEVER from an
    #: agent-supplied request field (which would be forgeable). Used by
    #: ``_mutate_phase`` to decide whether story-scoped session/locks are
    #: materialized for a fast story.
    load_story_context: Callable[[str, str], StoryContext | None] = (
        _load_story_context_via_story_surface
    )
