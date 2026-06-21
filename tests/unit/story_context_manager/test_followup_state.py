"""Tests for FK-24 exploration follow-up flags on StoryContext."""

from __future__ import annotations

from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType


def test_story_context_accepts_typed_implementation_followup_flags() -> None:
    ctx = StoryContext(
        project_key="test-project",
        story_id="TEST-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        implementation_required=True,
        closure_allowed=False,
        story_done=False,
        exploration_completed=True,
        execution_pending=True,
    )

    assert ctx.implementation_required is True
    assert ctx.closure_allowed is False
    assert ctx.story_done is False
    assert ctx.exploration_completed is True
    assert ctx.execution_pending is True


def test_concept_story_followup_flags_are_unset_by_default() -> None:
    ctx = StoryContext(
        project_key="test-project",
        story_id="TEST-002",
        story_type=StoryType.CONCEPT,
        execution_route=None,
    )

    assert ctx.implementation_required is None
    assert ctx.closure_allowed is None
    assert ctx.story_done is None
    assert ctx.exploration_completed is None
    assert ctx.execution_pending is None
