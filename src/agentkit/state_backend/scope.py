"""Scope helpers for canonical state persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext


@dataclass(frozen=True)
class StateScope:
    """Canonical scope for one story inside one project."""

    project_key: str
    story_id: str
    story_dir: Path


def _derive_project_key_from_story_dir(story_dir: Path) -> str:
    try:
        stories_root = story_dir.parent
        project_root = stories_root.parent
        if stories_root.name == "stories" and project_root.name:
            return project_root.name
    except IndexError:
        pass
    if story_dir.parent.name:
        return story_dir.parent.name
    return "default-project"


def project_key_for_context(ctx: StoryContext, story_dir: Path | None = None) -> str:
    """Derive a stable project key until explicit registration is wired through."""

    if ctx.project_root is not None:
        return ctx.project_root.name
    if ctx.worktree_path is not None:
        return ctx.worktree_path.parent.name
    if story_dir is not None:
        return _derive_project_key_from_story_dir(story_dir)
    return "default-project"


def scope_from_story_context(story_dir: Path, ctx: StoryContext) -> StateScope:
    """Build a canonical scope from an explicit story context."""

    return StateScope(
        project_key=project_key_for_context(ctx, story_dir),
        story_id=ctx.story_id,
        story_dir=story_dir,
    )


def scope_from_story_dir(story_dir: Path) -> StateScope:
    """Build a best-effort scope from the story directory layout."""

    return StateScope(
        project_key=_derive_project_key_from_story_dir(story_dir),
        story_id=story_dir.name,
        story_dir=story_dir,
    )


__all__ = [
    "StateScope",
    "project_key_for_context",
    "scope_from_story_context",
    "scope_from_story_dir",
]
