"""Repository surface for control-plane runtime lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.state_backend import (
    append_execution_event_global,
    delete_session_run_binding_global,
    load_control_plane_operation_global,
    load_session_run_binding_global,
    load_story_execution_lock_global,
    save_control_plane_operation_global,
    save_session_run_binding_global,
    save_story_execution_lock_global,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.state_backend import (
        ControlPlaneOperationRecord,
        ExecutionEventRecord,
        SessionRunBindingRecord,
        StoryExecutionLockRecord,
    )


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
