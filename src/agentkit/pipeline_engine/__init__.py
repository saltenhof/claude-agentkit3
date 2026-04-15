"""Pipeline engine component namespace."""

from __future__ import annotations

from agentkit.pipeline_engine.engine import EngineResult, PipelineEngine
from agentkit.pipeline_engine.lifecycle import (
    HandlerResult,
    NoOpHandler,
    PhaseHandler,
    PhaseHandlerRegistry,
)
from agentkit.pipeline_engine.runner import PipelineRunResult, run_pipeline

__all__ = [
    "EngineResult",
    "HandlerResult",
    "NoOpHandler",
    "PhaseHandler",
    "PhaseHandlerRegistry",
    "PipelineEngine",
    "PipelineRunResult",
    "run_pipeline",
]
