"""Unit tests for StageRegistry.stages_for / layer1_stages_for (FK-33 §33.2.4)."""

from __future__ import annotations

from agentkit.core_types import Severity
from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system.stage_registry import (
    ExecutionPolicy,
    StageDefinition,
    StageRegistry,
)


def _stage(stage_id: str, layer: int, types: set[StoryType]) -> StageDefinition:
    return StageDefinition(
        stage_id=stage_id,
        layer=layer,
        severity=Severity.BLOCKING,
        applies_to=frozenset(types),
        execution_policy=ExecutionPolicy.ALWAYS,
    )


class TestStagesFor:
    def test_default_registry_returns_all_for_implementation(self) -> None:
        registry = StageRegistry()
        impl = registry.stages_for(StoryType.IMPLEMENTATION)
        assert len(impl) >= 19
        assert all(StoryType.IMPLEMENTATION in s.applies_to for s in impl)

    def test_default_registry_returns_all_for_bugfix(self) -> None:
        registry = StageRegistry()
        bug = registry.stages_for(StoryType.BUGFIX)
        assert len(bug) >= 19

    def test_concept_and_research_get_no_stages(self) -> None:
        registry = StageRegistry()
        assert registry.stages_for(StoryType.CONCEPT) == []
        assert registry.stages_for(StoryType.RESEARCH) == []

    def test_filters_by_applies_to(self) -> None:
        registry = StageRegistry(
            stages=(
                _stage("a.one", 1, {StoryType.IMPLEMENTATION}),
                _stage("a.two", 1, {StoryType.BUGFIX}),
            )
        )
        impl = [s.stage_id for s in registry.stages_for(StoryType.IMPLEMENTATION)]
        bug = [s.stage_id for s in registry.stages_for(StoryType.BUGFIX)]
        assert impl == ["a.one"]
        assert bug == ["a.two"]

    def test_preserves_registry_order(self) -> None:
        registry = StageRegistry(
            stages=(
                _stage("z.first", 1, {StoryType.IMPLEMENTATION}),
                _stage("a.second", 1, {StoryType.IMPLEMENTATION}),
            )
        )
        ids = [s.stage_id for s in registry.stages_for(StoryType.IMPLEMENTATION)]
        assert ids == ["z.first", "a.second"]


class TestLayer1StagesFor:
    def test_filters_to_layer_1(self) -> None:
        registry = StageRegistry(
            stages=(
                _stage("l1", 1, {StoryType.IMPLEMENTATION}),
                _stage("l2", 2, {StoryType.IMPLEMENTATION}),
            )
        )
        ids = [
            s.stage_id
            for s in registry.layer1_stages_for(
                StoryType.IMPLEMENTATION, are_enabled=False
            )
        ]
        assert ids == ["l1"]

    def test_are_stage_excluded_when_disabled(self) -> None:
        registry = StageRegistry()
        off = {
            s.stage_id
            for s in registry.layer1_stages_for(
                StoryType.IMPLEMENTATION, are_enabled=False
            )
        }
        assert "are.gate" not in off

    def test_are_stage_included_when_enabled(self) -> None:
        registry = StageRegistry()
        on = {
            s.stage_id
            for s in registry.layer1_stages_for(
                StoryType.IMPLEMENTATION, are_enabled=True
            )
        }
        assert "are.gate" in on
