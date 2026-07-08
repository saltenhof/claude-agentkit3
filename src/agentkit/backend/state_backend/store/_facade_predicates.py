"""Predicate helpers built on canonical facade reads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.store import mappers
from agentkit.backend.state_backend.store._facade_runtime_records import (
    load_phase_snapshot,
    load_phase_state,
)
from agentkit.backend.state_backend.store._facade_story_metadata import (
    load_story_context,
)
from agentkit.backend.state_backend.verify_artifact_store import (
    backend_has_structural_artifact as backend_has_structural_artifact,
)
from agentkit.backend.state_backend.verify_artifact_store import (
    backend_has_structural_artifact_for_scope as backend_has_structural_artifact_for_scope,
)
from agentkit.backend.state_backend.verify_artifact_store import (
    backend_verify_decision_passed as backend_verify_decision_passed,
)
from agentkit.backend.state_backend.verify_artifact_store import (
    backend_verify_decision_passed_for_scope as backend_verify_decision_passed_for_scope,
)

if TYPE_CHECKING:
    from pathlib import Path



def backend_has_valid_context(story_dir: Path) -> bool:
    return load_story_context(story_dir) is not None


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return load_phase_state(story_dir) is not None


def backend_has_completed_snapshot(story_dir: Path, phase: str) -> bool:
    snapshot = load_phase_snapshot(story_dir, phase)
    return snapshot is not None and mappers.phase_snapshot_completed(snapshot)


__all__ = [
    "backend_has_valid_context",
    "backend_has_valid_phase_state",
    "backend_has_completed_snapshot",
    "backend_has_structural_artifact",
    "backend_has_structural_artifact_for_scope",
    "backend_verify_decision_passed",
    "backend_verify_decision_passed_for_scope",
]
