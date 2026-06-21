"""Test helpers for constructing complete FK-39 PhaseState objects."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agentkit.backend.pipeline_engine.phase_executor import (
    PHASE_STATE_SCHEMA_VERSION,
    PhaseState,
    PhaseStateMode,
    PhaseStateProducer,
)
from agentkit.backend.story_context_manager.types import StoryType


def make_phase_state(**overrides: Any) -> PhaseState:
    """Build a complete PhaseState for tests that only care about a few fields."""

    if "paused_reason" in overrides and "pause_reason" not in overrides:
        overrides["pause_reason"] = overrides.pop("paused_reason")

    now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    data: dict[str, Any] = {
        "schema_version": PHASE_STATE_SCHEMA_VERSION,
        "story_id": "AG3-001",
        "run_id": "11111111-1111-4111-8111-111111111111",
        "phase": "setup",
        "status": "pending",
        "mode": PhaseStateMode.EXECUTION,
        "story_type": StoryType.IMPLEMENTATION,
        "attempt": 1,
        "started_at": now,
        "phase_entered_at": now,
        "pause_reason": None,
        "escalation_reason": None,
        "warnings": [],
        "producer": PhaseStateProducer(type="test", name="phase-state-factory"),
    }
    data.update(overrides)
    return PhaseState(**data)
