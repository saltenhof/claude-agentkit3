"""Compatibility facade selecting the configured canonical state backend."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, cast

from agentkit.exceptions import CorruptStateError
from agentkit.state_backend.config import (
    StateBackendKind,
    load_state_backend_config,
)
from agentkit.state_backend.scope import (
    RuntimeStateScope,
    runtime_scope_from_state,
    scope_from_story_context,
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
    from agentkit.state_backend.records import (
        AttemptRecord,
        ControlPlaneOperationRecord,
        ExecutionEventRecord,
        ExecutionReport,
        QAFindingRecord,
        QAStageResultRecord,
        SessionRunBindingRecord,
        StoryExecutionLockRecord,
        StoryMetricsRecord,
    )
    from agentkit.story_context_manager.models import (
        PhaseSnapshot,
        PhaseState,
        StoryContext,
    )

JsonRecord = dict[str, object]
_SESSION_BINDING_UNSUPPORTED = (
    "Global session binding storage is unsupported by the active backend"
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


def _cast_json_record(value: object) -> JsonRecord | None:
    return cast("JsonRecord | None", value)


def load_json_safe(path: Path) -> JsonRecord | None:
    return _cast_json_record(_backend_module().load_json_safe(path))


def resolve_runtime_scope(story_dir: Path) -> RuntimeStateScope:
    """Resolve explicit canonical scope for one story and current run."""

    try:
        flow = load_flow_execution(story_dir)
    except CorruptStateError:
        flow = None
    if flow is not None:
        return RuntimeStateScope(
            project_key=flow.project_key,
            story_id=flow.story_id,
            story_dir=story_dir,
            run_id=flow.run_id,
            flow_id=flow.flow_id,
            attempt_no=flow.attempt_no,
        )

    try:
        ctx = load_story_context(story_dir)
    except CorruptStateError:
        ctx = None
    if ctx is not None:
        return runtime_scope_from_state(scope_from_story_context(story_dir, ctx))

    raise CorruptStateError(
        (
            "Cannot resolve runtime scope without canonical story context "
            "or flow execution"
        ),
        detail={
            "story_dir": str(story_dir),
            "story_id": story_dir.name,
        },
    )


def save_story_context(story_dir: Path, ctx: StoryContext) -> None:
    _backend_module().save_story_context(story_dir, ctx)


def load_story_context(story_dir: Path) -> StoryContext | None:
    return cast("StoryContext | None", _backend_module().load_story_context(story_dir))


def read_story_context_record(story_dir: Path) -> StoryContext | None:
    return cast(
        "StoryContext | None",
        _backend_module().read_story_context_record(story_dir),
    )


def save_phase_state(story_dir: Path, state: PhaseState) -> None:
    _backend_module().save_phase_state(story_dir, state)


def load_phase_state(story_dir: Path) -> PhaseState | None:
    return cast("PhaseState | None", _backend_module().load_phase_state(story_dir))


def read_phase_state_record(story_dir: Path) -> PhaseState | None:
    return cast(
        "PhaseState | None",
        _backend_module().read_phase_state_record(story_dir),
    )


def save_phase_snapshot(story_dir: Path, snapshot: PhaseSnapshot) -> None:
    _backend_module().save_phase_snapshot(story_dir, snapshot)


def load_phase_snapshot(story_dir: Path, phase: str) -> PhaseSnapshot | None:
    return cast(
        "PhaseSnapshot | None",
        _backend_module().load_phase_snapshot(story_dir, phase),
    )


def read_phase_snapshot_record(
    story_dir: Path,
    phase: str,
) -> PhaseSnapshot | None:
    return cast(
        "PhaseSnapshot | None",
        _backend_module().read_phase_snapshot_record(story_dir, phase),
    )


def save_attempt(story_dir: Path, attempt: AttemptRecord) -> None:
    _backend_module().save_attempt(story_dir, attempt)


def load_attempts(story_dir: Path, phase: str) -> list[AttemptRecord]:
    return cast(
        "list[AttemptRecord]",
        _backend_module().load_attempts(story_dir, phase),
    )


def append_execution_event(story_dir: Path, event: ExecutionEventRecord) -> None:
    _backend_module().append_execution_event(story_dir, event)


def append_execution_event_global(event: ExecutionEventRecord) -> None:
    backend = _backend_module()
    if not hasattr(backend, "append_execution_event_global"):
        raise RuntimeError(
            "Global execution-event append is unsupported by the active backend",
        )
    backend.append_execution_event_global(event)


def save_session_run_binding_global(record: SessionRunBindingRecord) -> None:
    backend = _backend_module()
    if not hasattr(backend, "save_session_run_binding_global"):
        raise RuntimeError(_SESSION_BINDING_UNSUPPORTED)
    backend.save_session_run_binding_global(record)


def load_session_run_binding_global(
    session_id: str,
) -> SessionRunBindingRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_session_run_binding_global"):
        raise RuntimeError(_SESSION_BINDING_UNSUPPORTED)
    return cast(
        "SessionRunBindingRecord | None",
        backend.load_session_run_binding_global(session_id),
    )


def delete_session_run_binding_global(session_id: str) -> None:
    backend = _backend_module()
    if not hasattr(backend, "delete_session_run_binding_global"):
        raise RuntimeError(_SESSION_BINDING_UNSUPPORTED)
    backend.delete_session_run_binding_global(session_id)


def save_story_execution_lock_global(record: StoryExecutionLockRecord) -> None:
    backend = _backend_module()
    if not hasattr(backend, "save_story_execution_lock_global"):
        raise RuntimeError(
            "Global story-execution locks are unsupported by the active backend",
        )
    backend.save_story_execution_lock_global(record)


def load_story_execution_lock_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> StoryExecutionLockRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_story_execution_lock_global"):
        raise RuntimeError(
            "Global story-execution locks are unsupported by the active backend",
        )
    return cast(
        "StoryExecutionLockRecord | None",
        backend.load_story_execution_lock_global(project_key, story_id, run_id),
    )


def save_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
) -> None:
    backend = _backend_module()
    if not hasattr(backend, "save_control_plane_operation_global"):
        raise RuntimeError(
            "Global control-plane operations are unsupported by the active backend",
        )
    backend.save_control_plane_operation_global(record)


def load_control_plane_operation_global(
    op_id: str,
) -> ControlPlaneOperationRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_control_plane_operation_global"):
        raise RuntimeError(
            "Global control-plane operations are unsupported by the active backend",
        )
    return cast(
        "ControlPlaneOperationRecord | None",
        backend.load_control_plane_operation_global(op_id),
    )


def load_execution_events(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    event_type: str | None = None,
) -> list[ExecutionEventRecord]:
    return cast(
        "list[ExecutionEventRecord]",
        _backend_module().load_execution_events(
            story_dir,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            event_type=event_type,
        ),
    )


def save_flow_execution(story_dir: Path, record: FlowExecution) -> None:
    _backend_module().save_flow_execution(story_dir, record)


def load_flow_execution(story_dir: Path) -> FlowExecution | None:
    return cast(
        "FlowExecution | None",
        _backend_module().load_flow_execution(story_dir),
    )


def save_node_execution_ledger(story_dir: Path, record: NodeExecutionLedger) -> None:
    _backend_module().save_node_execution_ledger(story_dir, record)


def load_node_execution_ledger(
    story_dir: Path,
    flow_id: str,
    node_id: str,
) -> NodeExecutionLedger | None:
    return cast(
        "NodeExecutionLedger | None",
        _backend_module().load_node_execution_ledger(
            story_dir,
            flow_id,
            node_id,
        ),
    )


def save_override_record(story_dir: Path, record: OverrideRecord) -> None:
    _backend_module().save_override_record(story_dir, record)


def load_override_records(story_dir: Path) -> list[OverrideRecord]:
    return cast(
        "list[OverrideRecord]",
        _backend_module().load_override_records(story_dir),
    )


def record_layer_artifacts(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    return cast(
        "tuple[str, ...]",
        _backend_module().record_layer_artifacts(
            story_dir,
            layer_results=layer_results,
            attempt_nr=attempt_nr,
            projection_dir=projection_dir,
        ),
    )


def record_verify_decision(
    story_dir: Path,
    *,
    decision: VerifyDecision,
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    return cast(
        "tuple[str, ...]",
        _backend_module().record_verify_decision(
            story_dir,
            decision=decision,
            attempt_nr=attempt_nr,
            projection_dir=projection_dir,
        ),
    )


def load_latest_verify_decision(
    story_dir: Path,
) -> JsonRecord | None:
    return _cast_json_record(_backend_module().load_latest_verify_decision(story_dir))


def load_latest_verify_decision_for_scope(
    scope: RuntimeStateScope,
) -> JsonRecord | None:
    return _cast_json_record(
        _backend_module().load_latest_verify_decision_for_scope(scope),
    )


def read_latest_verify_decision_record(
    story_dir: Path,
) -> JsonRecord | None:
    return _cast_json_record(
        _backend_module().read_latest_verify_decision_record(story_dir),
    )


def load_artifact_record(
    story_dir: Path,
    artifact_kind: str,
) -> JsonRecord | None:
    return _cast_json_record(
        _backend_module().load_artifact_record(story_dir, artifact_kind),
    )


def load_artifact_record_for_scope(
    scope: RuntimeStateScope,
    artifact_kind: str,
) -> JsonRecord | None:
    return _cast_json_record(
        _backend_module().load_artifact_record_for_scope(scope, artifact_kind),
    )


def read_artifact_record(
    story_dir: Path,
    artifact_kind: str,
) -> JsonRecord | None:
    return _cast_json_record(
        _backend_module().read_artifact_record(story_dir, artifact_kind),
    )


def record_closure_report(
    story_dir: Path,
    report: ExecutionReport,
    *,
    projection_dir: Path | None = None,
) -> Path:
    return cast(
        "Path",
        _backend_module().record_closure_report(
            story_dir,
            report,
            projection_dir=projection_dir,
        ),
    )


def upsert_story_metrics(story_dir: Path, metrics: StoryMetricsRecord) -> None:
    _backend_module().upsert_story_metrics(story_dir, metrics)


def load_story_metrics(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
) -> list[StoryMetricsRecord]:
    return cast(
        "list[StoryMetricsRecord]",
        _backend_module().load_story_metrics(
            story_dir,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
        ),
    )


def load_story_metrics_for_scope(
    scope: RuntimeStateScope,
) -> list[StoryMetricsRecord]:
    return cast(
        "list[StoryMetricsRecord]",
        _backend_module().load_story_metrics_for_scope(scope),
    )


def load_qa_stage_results(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAStageResultRecord]:
    return cast(
        "list[QAStageResultRecord]",
        _backend_module().load_qa_stage_results(
            story_dir,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            attempt_no=attempt_no,
            stage_id=stage_id,
        ),
    )


def load_qa_stage_results_for_scope(
    scope: RuntimeStateScope,
    *,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAStageResultRecord]:
    return cast(
        "list[QAStageResultRecord]",
        _backend_module().load_qa_stage_results_for_scope(
            scope,
            attempt_no=attempt_no,
            stage_id=stage_id,
        ),
    )


def load_qa_findings(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAFindingRecord]:
    return cast(
        "list[QAFindingRecord]",
        _backend_module().load_qa_findings(
            story_dir,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            attempt_no=attempt_no,
            stage_id=stage_id,
        ),
    )


def load_qa_findings_for_scope(
    scope: RuntimeStateScope,
    *,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAFindingRecord]:
    return cast(
        "list[QAFindingRecord]",
        _backend_module().load_qa_findings_for_scope(
            scope,
            attempt_no=attempt_no,
            stage_id=stage_id,
        ),
    )


def backend_has_valid_context(story_dir: Path) -> bool:
    return cast("bool", _backend_module().backend_has_valid_context(story_dir))


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return cast("bool", _backend_module().backend_has_valid_phase_state(story_dir))


def backend_has_completed_snapshot(story_dir: Path, phase: str) -> bool:
    return cast(
        "bool",
        _backend_module().backend_has_completed_snapshot(story_dir, phase),
    )


def backend_has_structural_artifact(story_dir: Path) -> bool:
    return cast("bool", _backend_module().backend_has_structural_artifact(story_dir))


def backend_has_structural_artifact_for_scope(scope: RuntimeStateScope) -> bool:
    return cast(
        "bool",
        _backend_module().backend_has_structural_artifact_for_scope(scope),
    )


def backend_verify_decision_passed(story_dir: Path) -> bool:
    return cast("bool", _backend_module().backend_verify_decision_passed(story_dir))


def backend_verify_decision_passed_for_scope(scope: RuntimeStateScope) -> bool:
    return cast(
        "bool",
        _backend_module().backend_verify_decision_passed_for_scope(scope),
    )
