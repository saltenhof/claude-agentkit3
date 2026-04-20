"""Pipeline orchestration -- engine, lifecycle, and state persistence.

Public API re-exports for the pipeline package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.pipeline.engine import EngineResult, PipelineEngine
from agentkit.pipeline.lifecycle import (
    HandlerResult,
    NoOpHandler,
    PhaseHandler,
    PhaseHandlerRegistry,
)
from agentkit.pipeline.runner import PipelineRunResult, run_pipeline
from agentkit.state_backend import (
    AttemptRecord,
    read_phase_state_record,
    read_story_context_record,
    save_phase_state,
    save_story_context,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import PhaseState, StoryContext


def load_phase_state(story_dir: Path) -> PhaseState | None:
    """Read the canonical phase-state record for one story."""

    return read_phase_state_record(story_dir)


def load_story_context(story_dir: Path) -> StoryContext | None:
    """Read the canonical story-context record for one story."""

    return read_story_context_record(story_dir)

__all__ = [
    "AttemptRecord",
    "EngineResult",
    "HandlerResult",
    "NoOpHandler",
    "PhaseHandler",
    "PhaseHandlerRegistry",
    "PipelineEngine",
    "PipelineRunResult",
    "load_phase_state",
    "load_story_context",
    "read_phase_state_record",
    "read_story_context_record",
    "run_pipeline",
    "save_phase_state",
    "save_story_context",
]
