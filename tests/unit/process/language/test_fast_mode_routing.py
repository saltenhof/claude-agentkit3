"""Fast-mode routing tests (AG3-018, DELTA-A + AC3/AC7, FK-24 §24.3.4).

A ``mode == fast`` story NEVER enters the Exploration phase: the workflow
transition guards and the routing-rule helpers both route Setup directly to
Implementation. Also covers AC7's model-layer fail-closed (fast only legal for
implementation/bugfix).
"""

from __future__ import annotations

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.pipeline_engine.phase_executor import PhaseState, PhaseStatus
from agentkit.process.language.definitions import IMPLEMENTATION_WORKFLOW
from agentkit.process.language.guards import mode_is_exploration
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.routing_rules import (
    get_phases_for_story,
    should_run_exploration,
)
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import StoryMode, StoryType


def _ctx(
    *,
    mode: WireStoryMode,
    execution_route: StoryMode | None = StoryMode.EXPLORATION,
    story_type: StoryType = StoryType.IMPLEMENTATION,
) -> StoryContext:
    return StoryContext(
        project_key="proj",
        story_id="AG3-001",
        story_type=story_type,
        execution_route=execution_route,
        mode=mode,
    )


def _setup_completed_state() -> PhaseState:
    return make_phase_state(
        story_id="AG3-001",
        phase="setup",
        status=PhaseStatus.COMPLETED,
    )


def test_fast_story_never_routes_to_exploration_guard() -> None:
    # Even with execution_route=EXPLORATION, fast mode fails the exploration
    # guard so setup -> implementation wins.
    ctx = _ctx(mode=WireStoryMode.FAST, execution_route=StoryMode.EXPLORATION)
    result = mode_is_exploration(ctx, _setup_completed_state())
    assert not result.passed
    assert "fast" in (result.reason or "").lower()


def test_standard_exploration_story_still_routes_to_exploration() -> None:
    ctx = _ctx(mode=WireStoryMode.STANDARD, execution_route=StoryMode.EXPLORATION)
    result = mode_is_exploration(ctx, _setup_completed_state())
    assert result.passed


def test_fast_story_setup_transition_targets_implementation() -> None:
    # The implementation workflow's setup transitions, evaluated in order, must
    # resolve to ``implementation`` for a fast story (exploration is skipped).
    ctx = _ctx(mode=WireStoryMode.FAST, execution_route=StoryMode.EXPLORATION)
    state = _setup_completed_state()
    transitions = IMPLEMENTATION_WORKFLOW.get_transitions_from("setup")
    target = None
    for transition in transitions:
        if transition.guard is None or transition.guard(ctx, state).passed:
            target = transition.target
            break
    assert target == "implementation"


def test_fast_story_phases_exclude_exploration() -> None:
    ctx = _ctx(mode=WireStoryMode.FAST, execution_route=StoryMode.EXPLORATION)
    assert "exploration" not in get_phases_for_story(ctx)
    assert not should_run_exploration(ctx)


def test_standard_exploration_story_includes_exploration() -> None:
    ctx = _ctx(mode=WireStoryMode.STANDARD, execution_route=StoryMode.EXPLORATION)
    assert "exploration" in get_phases_for_story(ctx)
    assert should_run_exploration(ctx)


# --- AC7: fast is fail-closed for concept/research (model layer) -------------


@pytest.mark.parametrize("story_type", [StoryType.CONCEPT, StoryType.RESEARCH])
def test_fast_mode_rejected_for_non_code_story_types(story_type: StoryType) -> None:
    with pytest.raises(ValueError, match="mode=fast"):
        StoryContext(
            project_key="proj",
            story_id="AG3-002",
            story_type=story_type,
            execution_route=None,
            mode=WireStoryMode.FAST,
        )


@pytest.mark.parametrize(
    "story_type", [StoryType.IMPLEMENTATION, StoryType.BUGFIX]
)
def test_fast_mode_allowed_for_code_story_types(story_type: StoryType) -> None:
    ctx = StoryContext(
        project_key="proj",
        story_id="AG3-003",
        story_type=story_type,
        execution_route=StoryMode.EXECUTION,
        mode=WireStoryMode.FAST,
    )
    assert ctx.mode is WireStoryMode.FAST
