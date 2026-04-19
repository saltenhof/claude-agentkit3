"""Compatibility facade selecting the configured canonical state backend."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from agentkit.state_backend.config import (
    StateBackendKind,
    load_state_backend_config,
)

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from agentkit.phase_state_store.models import (
        FlowExecution,
        NodeExecutionLedger,
        OverrideRecord,
    )
    from agentkit.qa.policy_engine.engine import VerifyDecision
    from agentkit.qa.protocols import LayerResult
    from agentkit.state_backend.records import AttemptRecord, ExecutionReport
    from agentkit.story_context_manager.models import (
        PhaseSnapshot,
        PhaseState,
        StoryContext,
    )


@lru_cache(maxsize=1)
def _backend_module() -> ModuleType:
    config = load_state_backend_config()
    if config.backend is StateBackendKind.SQLITE:
        from agentkit.state_backend import sqlite_store

        return sqlite_store

    from agentkit.state_backend import postgres_store

    return postgres_store


def reset_backend_cache_for_tests() -> None:
    """Clear cached backend selection for test-time env switching."""

    _backend_module.cache_clear()


def load_json_safe(path: Path) -> dict[str, object] | None:
    return _backend_module().load_json_safe(path)


def save_story_context(story_dir: Path, ctx: StoryContext) -> None:
    return _backend_module().save_story_context(story_dir, ctx)


def load_story_context(story_dir: Path):
    return _backend_module().load_story_context(story_dir)


def read_story_context_record(story_dir: Path):
    return _backend_module().read_story_context_record(story_dir)


def save_phase_state(story_dir: Path, state: PhaseState) -> None:
    return _backend_module().save_phase_state(story_dir, state)


def load_phase_state(story_dir: Path):
    return _backend_module().load_phase_state(story_dir)


def read_phase_state_record(story_dir: Path):
    return _backend_module().read_phase_state_record(story_dir)


def save_phase_snapshot(story_dir: Path, snapshot: PhaseSnapshot) -> None:
    return _backend_module().save_phase_snapshot(story_dir, snapshot)


def load_phase_snapshot(story_dir: Path, phase: str):
    return _backend_module().load_phase_snapshot(story_dir, phase)


def read_phase_snapshot_record(story_dir: Path, phase: str):
    return _backend_module().read_phase_snapshot_record(story_dir, phase)


def save_attempt(story_dir: Path, attempt: AttemptRecord) -> None:
    return _backend_module().save_attempt(story_dir, attempt)


def load_attempts(story_dir: Path, phase: str):
    return _backend_module().load_attempts(story_dir, phase)


def save_flow_execution(story_dir: Path, record: FlowExecution) -> None:
    return _backend_module().save_flow_execution(story_dir, record)


def load_flow_execution(story_dir: Path):
    return _backend_module().load_flow_execution(story_dir)


def save_node_execution_ledger(story_dir: Path, record: NodeExecutionLedger) -> None:
    return _backend_module().save_node_execution_ledger(story_dir, record)


def load_node_execution_ledger(story_dir: Path, flow_id: str, node_id: str):
    return _backend_module().load_node_execution_ledger(
        story_dir,
        flow_id,
        node_id,
    )


def save_override_record(story_dir: Path, record: OverrideRecord) -> None:
    return _backend_module().save_override_record(story_dir, record)


def load_override_records(story_dir: Path):
    return _backend_module().load_override_records(story_dir)


def record_layer_artifacts(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    attempt_nr: int,
):
    return _backend_module().record_layer_artifacts(
        story_dir,
        layer_results=layer_results,
        attempt_nr=attempt_nr,
    )


def record_verify_decision(
    story_dir: Path,
    *,
    decision: VerifyDecision,
    attempt_nr: int,
):
    return _backend_module().record_verify_decision(
        story_dir,
        decision=decision,
        attempt_nr=attempt_nr,
    )


def load_latest_verify_decision(story_dir: Path):
    return _backend_module().load_latest_verify_decision(story_dir)


def read_latest_verify_decision_record(story_dir: Path):
    return _backend_module().read_latest_verify_decision_record(story_dir)


def load_artifact_record(story_dir: Path, artifact_kind: str):
    return _backend_module().load_artifact_record(story_dir, artifact_kind)


def read_artifact_record(story_dir: Path, artifact_kind: str):
    return _backend_module().read_artifact_record(story_dir, artifact_kind)


def record_closure_report(story_dir: Path, report: ExecutionReport):
    return _backend_module().record_closure_report(story_dir, report)


def backend_has_valid_context(story_dir: Path) -> bool:
    return _backend_module().backend_has_valid_context(story_dir)


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return _backend_module().backend_has_valid_phase_state(story_dir)


def backend_has_completed_snapshot(story_dir: Path, phase: str) -> bool:
    return _backend_module().backend_has_completed_snapshot(story_dir, phase)


def backend_has_structural_artifact(story_dir: Path) -> bool:
    return _backend_module().backend_has_structural_artifact(story_dir)


def backend_verify_decision_passed(story_dir: Path) -> bool:
    return _backend_module().backend_verify_decision_passed(story_dir)
