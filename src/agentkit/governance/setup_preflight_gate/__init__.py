"""SetupPreflightGate component (BC 4 governance).

Owns the Setup phase handler — issue ingestion, StoryContext bootstrap,
preflight checks against StoryService and worktree provisioning. The
phase handler is registered on PipelineEngine's PhaseHandlerRegistry by
the orchestrator that wires the run.
"""

from __future__ import annotations

from agentkit.governance.setup_preflight_gate.context_builder import (
    build_story_context,
)
from agentkit.governance.setup_preflight_gate.phase import (
    SetupConfig,
    SetupPhaseHandler,
)
from agentkit.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightCheckResult,
    PreflightContext,
    PreflightResult,
    PreflightStatus,
    run_preflight,
)

__all__ = [
    "PreflightCheckId",
    "PreflightCheckResult",
    "PreflightContext",
    "PreflightResult",
    "PreflightStatus",
    "SetupConfig",
    "SetupPhaseHandler",
    "build_story_context",
    "run_preflight",
]
