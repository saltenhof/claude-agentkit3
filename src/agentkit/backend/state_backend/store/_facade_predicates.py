"""Predicate helpers built on canonical facade reads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.store import mappers
from agentkit.backend.state_backend.store._facade_qa_artifacts import (
    load_artifact_record,
    load_latest_verify_decision,
)
from agentkit.backend.state_backend.store._facade_runtime_records import (
    load_phase_snapshot,
    load_phase_state,
)
from agentkit.backend.state_backend.store._facade_story_metadata import (
    load_story_context,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.state_backend.scope import RuntimeStateScope


def backend_has_valid_context(story_dir: Path) -> bool:
    return load_story_context(story_dir) is not None


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return load_phase_state(story_dir) is not None


def backend_has_completed_snapshot(story_dir: Path, phase: str) -> bool:
    snapshot = load_phase_snapshot(story_dir, phase)
    return snapshot is not None and mappers.phase_snapshot_completed(snapshot)


def backend_has_structural_artifact(story_dir: Path) -> bool:
    record = load_artifact_record(story_dir, "structural")
    return record is not None


def backend_has_structural_artifact_for_scope(scope: RuntimeStateScope) -> bool:
    return backend_has_structural_artifact(scope.story_dir)


def backend_verify_decision_passed(story_dir: Path) -> bool:
    payload = load_latest_verify_decision(story_dir)
    if payload is None:
        return False
    status = payload.get("status")
    return isinstance(status, str) and bool(payload.get("passed")) and status == "PASS"


def backend_verify_decision_passed_for_scope(scope: RuntimeStateScope) -> bool:
    return backend_verify_decision_passed(scope.story_dir)


__all__ = [
    "backend_has_valid_context",
    "backend_has_valid_phase_state",
    "backend_has_completed_snapshot",
    "backend_has_structural_artifact",
    "backend_has_structural_artifact_for_scope",
    "backend_verify_decision_passed",
    "backend_verify_decision_passed_for_scope",
]
