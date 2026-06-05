"""Tests for the Bugfix story-type profile (AC6).

FK-23 §23.1: the mode-determination applies to Implementation AND Bugfix; a
Bugfix with low concept quality may route to exploration mode. The profile must
therefore allow ``StoryMode.EXPLORATION`` while keeping ``EXECUTION`` the
default and the profile ``phases`` tuple unchanged.
"""

from __future__ import annotations

import pytest

from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import (
    PROFILES,
    StoryMode,
    StoryType,
    get_profile,
)


def test_bugfix_allows_exploration_mode() -> None:
    profile = PROFILES[StoryType.BUGFIX]
    assert StoryMode.EXPLORATION in profile.allowed_modes
    assert StoryMode.EXECUTION in profile.allowed_modes


def test_bugfix_default_mode_stays_execution() -> None:
    assert get_profile(StoryType.BUGFIX).default_mode is StoryMode.EXECUTION


def test_bugfix_phases_unchanged() -> None:
    # Exploration is injected via the mode switch (routing_rules), NOT via the
    # profile phases tuple (AG3-045 §2.1.5).
    assert get_profile(StoryType.BUGFIX).phases == (
        "setup",
        "implementation",
        "closure",
    )


def test_bugfix_story_can_route_to_exploration() -> None:
    """Real path: a Bugfix StoryContext with EXPLORATION route now validates."""
    ctx = StoryContext(
        project_key="test-project",
        story_id="BUG-1",
        story_type=StoryType.BUGFIX,
        execution_route=StoryMode.EXPLORATION,
    )
    assert ctx.execution_route is StoryMode.EXPLORATION


def test_bugfix_execution_route_still_valid() -> None:
    ctx = StoryContext(
        project_key="test-project",
        story_id="BUG-2",
        story_type=StoryType.BUGFIX,
        execution_route=StoryMode.EXECUTION,
    )
    assert ctx.execution_route is StoryMode.EXECUTION


def test_invalid_route_still_rejected_for_bugfix() -> None:
    # ``None`` (no route) is not an allowed mode for code-producing bugfix
    # stories — the allowlist is still enforced after the EXPLORATION addition.
    with pytest.raises(ValueError, match="not allowed"):
        StoryContext(
            project_key="test-project",
            story_id="BUG-3",
            story_type=StoryType.BUGFIX,
            execution_route=None,
        )


def test_implementation_profile_retains_exploration() -> None:
    # Regression: the Implementation profile is unchanged.
    assert StoryMode.EXPLORATION in PROFILES[StoryType.IMPLEMENTATION].allowed_modes
