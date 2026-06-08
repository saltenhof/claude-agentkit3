"""Tests for the Bugfix story-type profile (AC6, AG3-057).

FK-23 §23.1 / AG3-057: the mode-determination applies to Implementation AND
Bugfix; a bugfix with a trigger (e.g. low concept quality / architecture impact)
routes into Exploration mode.  The profile must:
- allow ``StoryMode.EXPLORATION`` (unchanged since before AG3-057)
- keep ``EXECUTION`` as the default mode
- include ``"exploration"`` in the phases tuple (AG3-057: the workflow carries
  the exploration phase so routing_rules can remove it for EXECUTION-mode bugs)
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


def test_bugfix_phases_include_exploration() -> None:
    """AG3-057: bugfix profile phases now include exploration (FK-23 §23.1).

    The exploration phase is included in the profile so that
    ``routing_rules.get_phases_for_story`` can remove it for EXECUTION-route
    bugfixes via the same mechanism used for implementation stories — no
    separate code path needed.
    """
    assert get_profile(StoryType.BUGFIX).phases == (
        "setup",
        "exploration",
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
