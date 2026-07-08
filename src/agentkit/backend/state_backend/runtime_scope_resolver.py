"""Shared runtime-scope resolution for state-backend stores."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend.scope import (
    RuntimeStateScope,
    runtime_scope_from_state,
    scope_from_story_context,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
)

if TYPE_CHECKING:
    from pathlib import Path


def resolve_runtime_scope(story_dir: Path) -> RuntimeStateScope:
    """Resolve explicit canonical scope for one story and current run."""
    from agentkit.backend.state_backend.store import mappers

    backend = _backend_module()
    try:
        flow_row = backend.load_flow_execution_row(story_dir)
    except CorruptStateError:
        flow_row = None
    if flow_row is not None:
        flow = mappers.flow_execution_row_to_record(flow_row)
        return RuntimeStateScope(
            project_key=flow.project_key,
            story_id=flow.story_id,
            story_dir=story_dir,
            run_id=flow.run_id,
            flow_id=flow.flow_id,
            attempt_no=flow.attempt_no,
        )

    try:
        context_row = backend.load_story_context_row(story_dir)
    except CorruptStateError:
        context_row = None
    if context_row is not None:
        context = mappers.story_context_payload_to_record(
            str(context_row["payload_json"]),
            db_label=str(story_dir),
        )
        return runtime_scope_from_state(scope_from_story_context(story_dir, context))

    raise CorruptStateError(
        "Cannot resolve runtime scope without canonical story context or flow execution",
        detail={
            "story_dir": str(story_dir),
            "story_id": story_dir.name,
        },
    )


__all__ = ["resolve_runtime_scope"]
