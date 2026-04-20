"""Contract tests for story contract classification in StoryContext."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)


@pytest.mark.contract
class TestStoryContextContracts:
    """Protect the persisted story contract rules from silent drift."""

    def test_implementation_defaults_to_standard_contract(self) -> None:
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-201",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXPLORATION,
        )

        assert ctx.implementation_contract == ImplementationContract.STANDARD

    @pytest.mark.parametrize(
        ("story_type", "mode"),
        (
            (StoryType.CONCEPT, StoryMode.NOT_APPLICABLE),
            (StoryType.RESEARCH, StoryMode.NOT_APPLICABLE),
            (StoryType.BUGFIX, StoryMode.EXECUTION),
        ),
    )
    def test_non_implementation_contract_axis_remains_empty(
        self,
        story_type: StoryType,
        mode: StoryMode,
    ) -> None:
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-202",
            story_type=story_type,
            execution_route=mode,
        )

        assert ctx.implementation_contract is None

    @pytest.mark.parametrize(
        ("story_type", "mode"),
        (
            (StoryType.BUGFIX, StoryMode.EXECUTION),
            (StoryType.CONCEPT, StoryMode.NOT_APPLICABLE),
            (StoryType.RESEARCH, StoryMode.NOT_APPLICABLE),
        ),
    )
    def test_integration_stabilization_is_rejected_outside_implementation(
        self,
        story_type: StoryType,
        mode: StoryMode,
    ) -> None:
        with pytest.raises(ValidationError, match="implementation_contract"):
            StoryContext(
                project_key="test-project",
                story_id="AG3-203",
                story_type=story_type,
                execution_route=mode,
                implementation_contract=ImplementationContract.INTEGRATION_STABILIZATION,
            )

    def test_execution_route_alias_tracks_mode(self) -> None:
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-204",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )

        assert ctx.execution_route == StoryMode.EXECUTION
