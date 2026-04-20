"""Scope helpers for canonical state persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.phase_state_store.models import FlowExecution
    from agentkit.story_context_manager.models import StoryContext


@dataclass(frozen=True)
class StateScope:
    """Canonical scope for one story inside one project."""

    project_key: str
    story_id: str
    story_dir: Path


@dataclass(frozen=True)
class RuntimeStateScope(StateScope):
    """Canonical runtime scope including one concrete run when known."""

    run_id: str | None = None
    flow_id: str | None = None
    attempt_no: int | None = None


def scope_from_story_context(story_dir: Path, ctx: StoryContext) -> StateScope:
    """Build a canonical scope from a canonical story context."""

    return StateScope(
        project_key=ctx.project_key,
        story_id=ctx.story_id,
        story_dir=story_dir,
    )


def runtime_scope_from_state(
    scope: StateScope,
    *,
    flow: FlowExecution | None = None,
) -> RuntimeStateScope:
    """Attach optional run-scope information to a base state scope."""

    if flow is None:
        return RuntimeStateScope(
            project_key=scope.project_key,
            story_id=scope.story_id,
            story_dir=scope.story_dir,
        )
    return RuntimeStateScope(
        project_key=flow.project_key,
        story_id=flow.story_id,
        story_dir=scope.story_dir,
        run_id=flow.run_id,
        flow_id=flow.flow_id,
        attempt_no=flow.attempt_no,
    )


__all__ = [
    "RuntimeStateScope",
    "StateScope",
    "runtime_scope_from_state",
    "scope_from_story_context",
]
