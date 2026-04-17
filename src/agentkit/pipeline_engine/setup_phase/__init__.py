"""Setup phase component namespace."""

from __future__ import annotations

from agentkit.pipeline_engine.setup_phase.context_builder import build_story_context
from agentkit.pipeline_engine.setup_phase.phase import SetupConfig, SetupPhaseHandler
from agentkit.pipeline_engine.setup_phase.preflight import (
    PreflightResult,
    run_preflight,
)

__all__ = [
    "PreflightResult",
    "SetupConfig",
    "SetupPhaseHandler",
    "build_story_context",
    "run_preflight",
]
