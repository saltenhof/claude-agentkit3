"""Pipeline orchestration -- engine, lifecycle, and state persistence.

Public API re-exports for the pipeline package.
"""

from __future__ import annotations

from agentkit.phase_state_store import (
    AttemptRecord,
    load_phase_state,
    load_story_context,
    save_phase_state,
    save_story_context,
)
from agentkit.pipeline.engine import EngineResult, PipelineEngine
from agentkit.pipeline.lifecycle import (
    HandlerResult,
    NoOpHandler,
    PhaseHandler,
    PhaseHandlerRegistry,
)
from agentkit.pipeline.runner import PipelineRunResult, run_pipeline

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
    "run_pipeline",
    "save_phase_state",
    "save_story_context",
]
