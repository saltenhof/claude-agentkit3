"""Runtime constants split out to keep ``runtime.py`` below LOC budgets."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from agentkit.backend.control_plane.edge_commands import TAKEOVER_ERROR_RESULT_TYPES
from agentkit.backend.pipeline_engine.phase_executor import PhaseName

FreshnessClass = Literal["baseline_read", "guarded_read", "mutation"]

SYNC_AFTER_BY_CLASS = {
    "baseline_read": timedelta(minutes=5),
    "guarded_read": timedelta(minutes=2),
    "mutation": timedelta(seconds=45),
}

EDGE_COMMAND_FAILURE_RESULT_TYPES = TAKEOVER_ERROR_RESULT_TYPES | frozenset(
    {"command_error"}
)
PUSH_GATED_COMPLETION_PHASES: frozenset[str] = frozenset(
    {PhaseName.IMPLEMENTATION.value}
)
PUSH_BARRIER_BLOCKED_CODE = "push_barrier_unverified"
KEEP_FIELD: object = object()
