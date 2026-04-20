"""Unit tests for pipeline public exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

import agentkit.pipeline as pipeline_api
from agentkit.story_context_manager.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


def test_load_phase_state_delegates_to_canonical_reader(tmp_path: Path) -> None:
    expected = PhaseState(
        story_id="TEST-001",
        phase="setup",
        status=PhaseStatus.COMPLETED,
    )
    seen: list[Path] = []

    def fake_reader(story_dir: Path) -> PhaseState:
        seen.append(story_dir)
        return expected

    original = pipeline_api.read_phase_state_record
    pipeline_api.read_phase_state_record = fake_reader
    try:
        assert pipeline_api.load_phase_state(tmp_path) == expected
    finally:
        pipeline_api.read_phase_state_record = original

    assert seen == [tmp_path]


def test_load_story_context_delegates_to_canonical_reader(tmp_path: Path) -> None:
    expected = StoryContext(
        project_key="test-project",
        story_id="TEST-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        title="Pipeline API",
    )
    seen: list[Path] = []

    def fake_reader(story_dir: Path) -> StoryContext:
        seen.append(story_dir)
        return expected

    original = pipeline_api.read_story_context_record
    pipeline_api.read_story_context_record = fake_reader
    try:
        assert pipeline_api.load_story_context(tmp_path) == expected
    finally:
        pipeline_api.read_story_context_record = original

    assert seen == [tmp_path]
