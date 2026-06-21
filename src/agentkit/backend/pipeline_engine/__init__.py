"""Pipeline engine component namespace.

Owns the deterministic orchestration core: FlowExecution, NodeExecution,
AttemptRecord and the four-phase control flow (FK-07 §7.4.1). Phase
handler implementations live in their owning bounded contexts
(``agentkit.backend.governance.setup_preflight_gate``, ``agentkit.backend.exploration``,
``agentkit.backend.implementation``, ``agentkit.backend.closure``) and are registered on
``PhaseHandlerRegistry`` by the orchestrator that wires the run.
"""

from __future__ import annotations

from agentkit.backend.pipeline_engine.engine import EngineResult, PipelineEngine
from agentkit.backend.pipeline_engine.lifecycle import (
    HandlerResult,
    NoOpHandler,
    PhaseHandler,
    PhaseHandlerRegistry,
)
from agentkit.backend.pipeline_engine.phase_executor.records import AttemptRecord
from agentkit.backend.pipeline_engine.runner import PipelineRunResult, run_pipeline
from agentkit.backend.pipeline_engine.runtime_state import EngineRuntimeState

__all__ = [
    "AttemptRecord",
    "EngineResult",
    "EngineRuntimeState",
    "HandlerResult",
    "NoOpHandler",
    "PhaseHandler",
    "PhaseHandlerRegistry",
    "PipelineEngine",
    "PipelineRunResult",
    "run_pipeline",
]
