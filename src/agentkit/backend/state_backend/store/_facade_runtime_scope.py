"""Runtime scope resolution helpers for the store facade."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend.scope import (
    RuntimeStateScope,
    runtime_scope_from_state,
    scope_from_story_context,
)
from agentkit.backend.state_backend.store._facade_runtime_records import (
    load_flow_execution,
)
from agentkit.backend.state_backend.store._facade_story_metadata import (
    load_story_context,
)

if TYPE_CHECKING:
    from pathlib import Path


def resolve_runtime_scope(story_dir: Path) -> RuntimeStateScope:
    """Resolve explicit canonical scope for one story and current run."""

    try:
        flow = load_flow_execution(story_dir)
    except CorruptStateError:
        flow = None
    if flow is not None:
        return RuntimeStateScope(
            project_key=flow.project_key,
            story_id=flow.story_id,
            story_dir=story_dir,
            run_id=flow.run_id,
            flow_id=flow.flow_id,
            attempt_no=flow.attempt_no,
        )

    try:
        ctx = load_story_context(story_dir)
    except CorruptStateError:
        ctx = None
    if ctx is not None:
        return runtime_scope_from_state(scope_from_story_context(story_dir, ctx))

    raise CorruptStateError(
        ("Cannot resolve runtime scope without canonical story context or flow execution"),
        detail={
            "story_dir": str(story_dir),
            "story_id": story_dir.name,
        },
    )


__all__ = [
    "resolve_runtime_scope",
]
