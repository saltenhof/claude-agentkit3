"""Compatibility re-export for canonical runtime state APIs.

The canonical implementation now lives in :mod:`agentkit.state_backend`.
This module remains as a stable import surface for older runtime code and tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.state_backend import (
    AttemptRecord,
    atomic_write_json,
    load_attempts,
    read_phase_snapshot_record,
    read_phase_state_record,
    read_story_context_record,
    save_attempt,
    save_phase_snapshot,
    save_phase_state,
    save_story_context,
)
from agentkit.state_backend.exports import read_projection_json_object

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import (
        PhaseSnapshot,
        PhaseState,
        StoryContext,
    )


def load_phase_state(story_dir: Path) -> PhaseState | None:
    """Compatibility wrapper over the canonical phase-state reader."""

    return read_phase_state_record(story_dir)


def load_story_context(story_dir: Path) -> StoryContext | None:
    """Compatibility wrapper over the canonical story-context reader."""

    return read_story_context_record(story_dir)


def load_phase_snapshot(story_dir: Path, phase: str) -> PhaseSnapshot | None:
    """Compatibility wrapper over the canonical phase-snapshot reader."""

    return read_phase_snapshot_record(story_dir, phase)


def load_json_safe(path: Path) -> dict[str, object] | None:
    """Compatibility wrapper for non-canonical projection reads."""

    return read_projection_json_object(path)

__all__ = [
    "AttemptRecord",
    "atomic_write_json",
    "load_attempts",
    "load_phase_snapshot",
    "load_phase_state",
    "load_story_context",
    "save_attempt",
    "save_phase_snapshot",
    "save_phase_state",
    "save_story_context",
    "load_json_safe",
]
