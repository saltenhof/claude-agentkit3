"""Pipeline engine component namespace."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
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

_LAZY_LIFECYCLE = {"HandlerResult", "NoOpHandler", "PhaseHandler", "PhaseHandlerRegistry"}
_LAZY_RUNNER = {"PipelineRunResult", "run_pipeline"}
_LAZY_ENGINE = {"EngineResult", "PipelineEngine"}


def __getattr__(name: str) -> object:
    """Lazy re-exports to avoid circular import with pipeline.engine."""
    if name in _LAZY_LIFECYCLE:
        from agentkit.pipeline_engine.lifecycle import (  # noqa: PLC0415
            HandlerResult,
            NoOpHandler,
            PhaseHandler,
            PhaseHandlerRegistry,
        )

        globals()["HandlerResult"] = HandlerResult
        globals()["NoOpHandler"] = NoOpHandler
        globals()["PhaseHandler"] = PhaseHandler
        globals()["PhaseHandlerRegistry"] = PhaseHandlerRegistry
        return globals()[name]

    if name in _LAZY_RUNNER:
        from agentkit.pipeline_engine.runner import (  # noqa: PLC0415
            PipelineRunResult,
            run_pipeline,
        )

        globals()["PipelineRunResult"] = PipelineRunResult
        globals()["run_pipeline"] = run_pipeline
        return globals()[name]

    if name in _LAZY_ENGINE:
        from agentkit.pipeline.engine import EngineResult, PipelineEngine  # noqa: PLC0415

        globals()["EngineResult"] = EngineResult
        globals()["PipelineEngine"] = PipelineEngine
        return globals()[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
