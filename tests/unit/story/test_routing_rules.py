"""Unit tests for agentkit.story.routing_rules."""

from __future__ import annotations

from agentkit.story.models import StoryContext
from agentkit.story.routing_rules import (
    get_phases_for_story,
    requires_merge,
    requires_worktree,
    should_run_exploration,
    should_run_full_qa,
)
from agentkit.story.types import StoryMode, StoryType


def _make_context(
    story_type: StoryType,
    mode: StoryMode | None = None,
) -> StoryContext:
    """Helper to create a minimal StoryContext for testing."""
    from agentkit.story.types import get_profile

    if mode is None:
        mode = get_profile(story_type).default_mode
    return StoryContext(
        story_id="TEST-001",
        story_type=story_type,
        mode=mode,
    )


class TestGetPhasesForStory:
    """Tests for get_phases_for_story."""

    def test_implementation_exploration_mode(self) -> None:
        ctx = _make_context(StoryType.IMPLEMENTATION, StoryMode.EXPLORATION)
        phases = get_phases_for_story(ctx)
        assert phases == [
            "setup",
            "exploration",
            "implementation",
            "verify",
            "closure",
        ]

    def test_implementation_execution_mode_skips_exploration(self) -> None:
        ctx = _make_context(StoryType.IMPLEMENTATION, StoryMode.EXECUTION)
        phases = get_phases_for_story(ctx)
        assert phases == ["setup", "implementation", "verify", "closure"]
        assert "exploration" not in phases

    def test_bugfix(self) -> None:
        ctx = _make_context(StoryType.BUGFIX)
        phases = get_phases_for_story(ctx)
        assert phases == ["setup", "implementation", "verify", "closure"]

    def test_concept(self) -> None:
        ctx = _make_context(StoryType.CONCEPT)
        phases = get_phases_for_story(ctx)
        assert phases == ["setup", "implementation", "verify", "closure"]

    def test_research(self) -> None:
        ctx = _make_context(StoryType.RESEARCH)
        phases = get_phases_for_story(ctx)
        assert phases == ["setup", "implementation", "closure"]

    def test_all_types_start_with_setup(self) -> None:
        for story_type in StoryType:
            ctx = _make_context(story_type)
            phases = get_phases_for_story(ctx)
            assert phases[0] == "setup"

    def test_code_types_end_with_closure(self) -> None:
        for story_type in StoryType:
            ctx = _make_context(story_type)
            phases = get_phases_for_story(ctx)
            assert phases[-1] == "closure"


class TestShouldRunExploration:
    """Tests for should_run_exploration."""

    def test_implementation_exploration_mode(self) -> None:
        ctx = _make_context(StoryType.IMPLEMENTATION, StoryMode.EXPLORATION)
        assert should_run_exploration(ctx) is True

    def test_implementation_execution_mode(self) -> None:
        ctx = _make_context(StoryType.IMPLEMENTATION, StoryMode.EXECUTION)
        assert should_run_exploration(ctx) is False

    def test_bugfix_never_explores(self) -> None:
        ctx = _make_context(StoryType.BUGFIX)
        assert should_run_exploration(ctx) is False

    def test_concept_never_explores(self) -> None:
        ctx = _make_context(StoryType.CONCEPT)
        assert should_run_exploration(ctx) is False

    def test_research_never_explores(self) -> None:
        ctx = _make_context(StoryType.RESEARCH)
        assert should_run_exploration(ctx) is False


class TestShouldRunFullQa:
    """Tests for should_run_full_qa."""

    def test_implementation_uses_full_qa(self) -> None:
        ctx = _make_context(StoryType.IMPLEMENTATION)
        assert should_run_full_qa(ctx) is True

    def test_bugfix_uses_full_qa(self) -> None:
        ctx = _make_context(StoryType.BUGFIX)
        assert should_run_full_qa(ctx) is True

    def test_concept_no_full_qa(self) -> None:
        ctx = _make_context(StoryType.CONCEPT)
        assert should_run_full_qa(ctx) is False

    def test_research_no_full_qa(self) -> None:
        ctx = _make_context(StoryType.RESEARCH)
        assert should_run_full_qa(ctx) is False


class TestRequiresWorktree:
    """Tests for requires_worktree."""

    def test_implementation_needs_worktree(self) -> None:
        ctx = _make_context(StoryType.IMPLEMENTATION)
        assert requires_worktree(ctx) is True

    def test_bugfix_needs_worktree(self) -> None:
        ctx = _make_context(StoryType.BUGFIX)
        assert requires_worktree(ctx) is True

    def test_concept_no_worktree(self) -> None:
        ctx = _make_context(StoryType.CONCEPT)
        assert requires_worktree(ctx) is False

    def test_research_no_worktree(self) -> None:
        ctx = _make_context(StoryType.RESEARCH)
        assert requires_worktree(ctx) is False


class TestRequiresMerge:
    """Tests for requires_merge."""

    def test_implementation_needs_merge(self) -> None:
        ctx = _make_context(StoryType.IMPLEMENTATION)
        assert requires_merge(ctx) is True

    def test_bugfix_needs_merge(self) -> None:
        ctx = _make_context(StoryType.BUGFIX)
        assert requires_merge(ctx) is True

    def test_concept_no_merge(self) -> None:
        ctx = _make_context(StoryType.CONCEPT)
        assert requires_merge(ctx) is False

    def test_research_no_merge(self) -> None:
        ctx = _make_context(StoryType.RESEARCH)
        assert requires_merge(ctx) is False
