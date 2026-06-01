"""Repository facade: selects the configured driver and applies mappers.

This module provides the canonical public API for state persistence.
All BC-Record <-> dict-row conversions happen here via ``mappers``.
Drivers (postgres_store, sqlite_store) only handle raw ``dict[str, Any]`` rows.
"""

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
from agentkit.state_backend.store import mappers

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType
    from uuid import UUID

    from agentkit.auth.entities import ProjectApiToken
    from agentkit.closure.execution_report.records import ExecutionReport
    from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.control_plane.records import (
        ControlPlaneOperationRecord,
        SessionRunBindingRecord,
    )
    from agentkit.execution_planning.entities import (
        ParallelizationConfig,
        StoryDependency,
        StoryDependencyKind,
    )
    from agentkit.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.phase_state_store.models import (
        FlowExecution,
        NodeExecutionLedger,
        OverrideRecord,
    )
    from agentkit.pipeline_engine.phase_executor.records import AttemptRecord
    from agentkit.project_management.entities import Project
    from agentkit.requirements_coverage.models import (
        StoryAreLink,
        StoryAreLinkKind,
    )
    from agentkit.story_context_manager.models import (
        PhaseSnapshot,
        PhaseState,
        StoryContext,
    )
    from agentkit.telemetry.contract.records import ExecutionEventRecord
    from agentkit.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.verify_system.protocols import LayerResult
    from agentkit.verify_system.stage_registry.records import (
        QAFindingRecord,
        QAStageResultRecord,
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


# ---------------------------------------------------------------------------
# StoryContext
# ---------------------------------------------------------------------------


def save_story_context(story_dir: Path, ctx: StoryContext) -> None:
    row = mappers.story_context_to_row(ctx)
    _backend_module().save_story_context_row(story_dir, row)


def save_story_context_global(store_dir: Path | None, ctx: StoryContext) -> None:
    row = mappers.story_context_to_row(ctx)
    _backend_module().save_story_context_global_row(store_dir, row)


def load_story_context(story_dir: Path) -> StoryContext | None:
    row = _backend_module().load_story_context_row(story_dir)
    if row is None:
        return None
    return mappers.story_context_payload_to_record(
        str(row["payload_json"]),
        db_label=str(story_dir),
    )


def load_story_context_global(
    project_key: str,
    story_id: str,
    store_dir: Path | None = None,
) -> StoryContext | None:
    backend = _backend_module()
    if not hasattr(backend, "load_story_context_global_row"):
        raise RuntimeError(
            "Global story-context reads are unsupported by the active backend",
        )
    row = backend.load_story_context_global_row(store_dir, project_key, story_id)
    if row is None:
        return None
    return mappers.story_context_payload_to_record(
        str(row["payload_json"]),
        db_label="postgres",
    )


def load_story_context_by_story_number_global(
    store_dir: Path | None,
    project_key: str,
    story_number: int,
) -> StoryContext | None:
    row = _backend_module().load_story_context_by_story_number_row(
        store_dir,
        project_key,
        story_number,
    )
    if row is None:
        return None
    return mappers.story_context_payload_to_record(
        str(row["payload_json"]),
        db_label="story_contexts",
    )


def load_story_context_by_uuid_global(
    store_dir: Path | None,
    story_uuid: UUID,
) -> StoryContext | None:
    row = _backend_module().load_story_context_by_uuid_row(
        store_dir,
        str(story_uuid),
    )
    if row is None:
        return None
    return mappers.story_context_payload_to_record(
        str(row["payload_json"]),
        db_label="story_contexts",
    )


def load_story_contexts_global(
    project_key: str,
    store_dir: Path | None = None,
) -> list[StoryContext]:
    backend = _backend_module()
    if not hasattr(backend, "load_story_context_rows_global"):
        raise RuntimeError(
            "Global story-context reads are unsupported by the active backend",
        )
    rows = backend.load_story_context_rows_global(store_dir, project_key)
    result: list[StoryContext] = []
    for row in rows:
        result.append(
            mappers.story_context_payload_to_record(
                str(row["payload_json"]),
                db_label="postgres",
            )
        )
    return result


def read_story_context_record(story_dir: Path) -> StoryContext | None:
    return load_story_context(story_dir)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


def save_project(project: Project, store_dir: Path | None = None) -> None:
    row = mappers.project_to_row(project)
    _backend_module().save_project_row(store_dir, row)


def load_project(key: str, store_dir: Path | None = None) -> Project | None:
    row = _backend_module().load_project_row(store_dir, key)
    if row is None:
        return None
    return mappers.project_row_to_entity(row)


def load_projects(
    store_dir: Path | None = None,
    *,
    include_archived: bool = False,
) -> list[Project]:
    rows = _backend_module().load_project_rows(
        store_dir,
        include_archived=include_archived,
    )
    return [mappers.project_row_to_entity(row) for row in rows]


def load_project_by_story_id_prefix(
    story_id_prefix: str,
    store_dir: Path | None = None,
) -> Project | None:
    row = _backend_module().load_project_row_by_story_id_prefix(
        store_dir,
        story_id_prefix,
    )
    if row is None:
        return None
    return mappers.project_row_to_entity(row)


# ---------------------------------------------------------------------------
# Project API tokens
# ---------------------------------------------------------------------------


def save_project_api_token(
    token: ProjectApiToken,
    store_dir: Path | None = None,
) -> None:
    row = mappers.project_api_token_to_row(token)
    _backend_module().save_project_api_token_row(store_dir, row)


def load_project_api_token(
    token_id: str,
    store_dir: Path | None = None,
) -> ProjectApiToken | None:
    row = _backend_module().load_project_api_token_row(store_dir, token_id)
    if row is None:
        return None
    return mappers.project_api_token_row_to_entity(row)


def load_project_api_token_by_hash(
    token_hash: str,
    store_dir: Path | None = None,
) -> ProjectApiToken | None:
    row = _backend_module().load_project_api_token_row_by_hash(store_dir, token_hash)
    if row is None:
        return None
    return mappers.project_api_token_row_to_entity(row)


def load_project_api_tokens_for_project(
    project_key: str,
    store_dir: Path | None = None,
) -> list[ProjectApiToken]:
    rows = _backend_module().load_project_api_token_rows_for_project(
        store_dir,
        project_key,
    )
    return [mappers.project_api_token_row_to_entity(row) for row in rows]


# ---------------------------------------------------------------------------
# Execution planning
# ---------------------------------------------------------------------------


def save_story_dependency(
    project_key: str,
    edge: StoryDependency,
    store_dir: Path | None = None,
) -> None:
    row = mappers.story_dependency_to_row(edge, project_key=project_key)
    _backend_module().save_story_dependency_row(store_dir, row)


def load_story_dependencies(
    project_key: str,
    store_dir: Path | None = None,
) -> list[StoryDependency]:
    rows = _backend_module().load_story_dependency_rows(store_dir, project_key)
    return [mappers.story_dependency_row_to_entity(row) for row in rows]


def load_story_dependency_rows_for_story(
    story_id: str,
    store_dir: Path | None = None,
) -> list[StoryDependency]:
    rows = _backend_module().load_story_dependency_rows_for_story(store_dir, story_id)
    return [mappers.story_dependency_row_to_entity(row) for row in rows]


def delete_story_dependency(
    story_id: str,
    depends_on_story_id: str,
    kind: StoryDependencyKind,
    store_dir: Path | None = None,
) -> int:
    return int(
        _backend_module().delete_story_dependency_row(
            store_dir,
            story_id,
            depends_on_story_id,
            kind.value,
        ),
    )


def load_parallelization_config(
    project_key: str,
    store_dir: Path | None = None,
) -> ParallelizationConfig | None:
    row = _backend_module().load_parallelization_config_row(store_dir, project_key)
    if row is None:
        return None
    return mappers.parallelization_config_row_to_entity(row)


def save_parallelization_config(
    config: ParallelizationConfig,
    store_dir: Path | None = None,
) -> None:
    row = mappers.parallelization_config_to_row(config)
    _backend_module().save_parallelization_config_row(store_dir, row)


# ---------------------------------------------------------------------------
# Requirements coverage
# ---------------------------------------------------------------------------


def save_story_are_link(
    link: StoryAreLink,
    store_dir: Path | None = None,
) -> None:
    row = mappers.story_are_link_to_row(link)
    _backend_module().save_story_are_link_row(store_dir, row)


def load_story_are_links(
    story_id: str,
    store_dir: Path | None = None,
) -> list[StoryAreLink]:
    rows = _backend_module().load_story_are_link_rows(store_dir, story_id)
    return [mappers.story_are_link_row_to_entity(row) for row in rows]


def update_story_are_link_kind(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    old_kind: StoryAreLinkKind,
    new_kind: StoryAreLinkKind,
) -> StoryAreLink | None:
    row = _backend_module().update_story_are_link_kind_row(
        store_dir,
        story_id,
        are_item_id,
        old_kind.value,
        new_kind.value,
    )
    if row is None:
        return None
    return mappers.story_are_link_row_to_entity(row)


def delete_story_are_link(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    kind: StoryAreLinkKind,
) -> int:
    return int(
        _backend_module().delete_story_are_link_row(
            store_dir,
            story_id,
            are_item_id,
            kind.value,
        ),
    )


# ---------------------------------------------------------------------------
# PhaseState
# ---------------------------------------------------------------------------


def save_phase_state(story_dir: Path, state: PhaseState) -> None:
    row = mappers.phase_state_to_row(state)
    _backend_module().save_phase_state_row(story_dir, row)


def load_phase_state(story_dir: Path) -> PhaseState | None:
    row = _backend_module().load_phase_state_row(story_dir)
    if row is None:
        return None
    return mappers.phase_state_payload_to_record(
        str(row["payload_json"]),
        db_label=str(story_dir),
    )


def load_phase_state_global(
    story_id: str,
    store_dir: Path | None = None,
) -> PhaseState | None:
    backend = _backend_module()
    if not hasattr(backend, "load_phase_state_global_row"):
        raise RuntimeError(
            "Global phase-state reads are unsupported by the active backend",
        )
    row = backend.load_phase_state_global_row(store_dir, story_id)
    if row is None:
        return None
    return mappers.phase_state_payload_to_record(
        str(row["payload_json"]),
        db_label="postgres",
    )


def read_phase_state_record(story_dir: Path) -> PhaseState | None:
    return load_phase_state(story_dir)


# ---------------------------------------------------------------------------
# PhaseSnapshot
# ---------------------------------------------------------------------------


def save_phase_snapshot(story_dir: Path, snapshot: PhaseSnapshot) -> None:
    row = mappers.phase_snapshot_to_row(snapshot)
    _backend_module().save_phase_snapshot_row(story_dir, row)


def load_phase_snapshot(story_dir: Path, phase: str) -> PhaseSnapshot | None:
    row = _backend_module().load_phase_snapshot_row(story_dir, phase)
    if row is None:
        return None
    return mappers.phase_snapshot_payload_to_record(
        str(row["payload_json"]),
        phase,
        db_label=str(story_dir),
    )


def read_phase_snapshot_record(
    story_dir: Path,
    phase: str,
) -> PhaseSnapshot | None:
    return load_phase_snapshot(story_dir, phase)


# ---------------------------------------------------------------------------
# AttemptRecord
# ---------------------------------------------------------------------------


def save_attempt(story_dir: Path, attempt: AttemptRecord) -> None:
    row = mappers.attempt_record_to_row(attempt)
    _backend_module().save_attempt_row(story_dir, row)


def load_attempts(
    story_dir: Path,
    phase: str,
    *,
    run_id: str | None = None,
) -> list[AttemptRecord]:
    """Load AttemptRecords for a story+phase, optionally narrowed to a run.

    Fail-closed: invalide DB-Zeilen (CHECK-Constraint-Drift,
    Schema-Mismatch zwischen Backend und Mapper, korrupte JSON-Payloads)
    propagieren ``pydantic.ValidationError`` / ``ValueError`` an den
    Aufrufer. Frueher hat ein ``except`` defective rows still
    geschluckt — das maskierte echte Inkonsistenzen
    (vgl. AG3-025 Re-Review Befund 1).
    """

    rows = _backend_module().load_attempt_rows(story_dir, phase, run_id=run_id)
    return [mappers.attempt_row_to_record(row) for row in rows]


# ---------------------------------------------------------------------------
# ExecutionEventRecord
# ---------------------------------------------------------------------------


def append_execution_event(story_dir: Path, event: ExecutionEventRecord) -> None:
    row = mappers.execution_event_to_row(event)
    _backend_module().append_execution_event_row(story_dir, row)


def append_execution_event_global(event: ExecutionEventRecord) -> None:
    backend = _backend_module()
    if not hasattr(backend, "append_execution_event_global_row"):
        raise RuntimeError(
            "Global execution-event append is unsupported by the active backend",
        )
    row = mappers.execution_event_to_row(event)
    backend.append_execution_event_global_row(row)


def load_execution_events(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    event_type: str | None = None,
) -> list[ExecutionEventRecord]:
    rows = _backend_module().load_execution_event_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        event_type=event_type,
    )
    return [mappers.execution_event_row_to_record(row) for row in rows]


def load_execution_events_global(
    project_key: str,
    story_id: str,
    *,
    run_id: str | None = None,
    event_type: str | None = None,
    limit: int | None = None,
) -> list[ExecutionEventRecord]:
    backend = _backend_module()
    if not hasattr(backend, "load_execution_event_rows_global"):
        raise RuntimeError(
            "Global execution-event reads are unsupported by the active backend",
        )
    rows = backend.load_execution_event_rows_global(
        project_key,
        story_id,
        run_id=run_id,
        event_type=event_type,
        limit=limit,
    )
    return [mappers.execution_event_row_to_record(row) for row in rows]


def load_execution_events_for_project_global(
    project_key: str,
    *,
    limit: int | None = None,
) -> list[ExecutionEventRecord]:
    backend = _backend_module()
    if not hasattr(backend, "load_execution_event_rows_for_project_global"):
        raise RuntimeError(
            "Global project execution-event reads are unsupported by the active backend",
        )
    rows = backend.load_execution_event_rows_for_project_global(
        project_key,
        limit=limit,
    )
    return [mappers.execution_event_row_to_record(row) for row in rows]


# ---------------------------------------------------------------------------
# SessionRunBindingRecord
# ---------------------------------------------------------------------------


def save_session_run_binding_global(record: SessionRunBindingRecord) -> None:
    backend = _backend_module()
    if not hasattr(backend, "save_session_run_binding_global_row"):
        raise RuntimeError(_SESSION_BINDING_UNSUPPORTED)
    row = mappers.session_binding_to_row(record)
    backend.save_session_run_binding_global_row(row)


def load_session_run_binding_global(
    session_id: str,
) -> SessionRunBindingRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_session_run_binding_global_row"):
        raise RuntimeError(_SESSION_BINDING_UNSUPPORTED)
    row = backend.load_session_run_binding_global_row(session_id)
    if row is None:
        return None
    return mappers.session_binding_row_to_record(row)


def delete_session_run_binding_global(session_id: str) -> None:
    backend = _backend_module()
    if not hasattr(backend, "delete_session_run_binding_global"):
        raise RuntimeError(_SESSION_BINDING_UNSUPPORTED)
    backend.delete_session_run_binding_global(session_id)


# ---------------------------------------------------------------------------
# StoryExecutionLockRecord
# ---------------------------------------------------------------------------


def save_story_execution_lock_global(record: StoryExecutionLockRecord) -> None:
    backend = _backend_module()
    if not hasattr(backend, "save_story_execution_lock_global_row"):
        raise RuntimeError(
            "Global story-execution locks are unsupported by the active backend",
        )
    row = mappers.execution_lock_to_row(record)
    backend.save_story_execution_lock_global_row(row)


def load_story_execution_lock_global(
    project_key: str,
    story_id: str,
    run_id: str,
    lock_type: str = "story_execution",
) -> StoryExecutionLockRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_story_execution_lock_global_row"):
        raise RuntimeError(
            "Global story-execution locks are unsupported by the active backend",
        )
    row = backend.load_story_execution_lock_global_row(
        project_key,
        story_id,
        run_id,
        lock_type,
    )
    if row is None:
        return None
    return mappers.execution_lock_row_to_record(row)


# ---------------------------------------------------------------------------
# ControlPlaneOperationRecord
# ---------------------------------------------------------------------------


def save_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
) -> None:
    backend = _backend_module()
    if not hasattr(backend, "save_control_plane_operation_global_row"):
        raise RuntimeError(
            "Global control-plane operations are unsupported by the active backend",
        )
    row = mappers.control_plane_op_to_row(record)
    backend.save_control_plane_operation_global_row(row)


def load_control_plane_operation_global(
    op_id: str,
) -> ControlPlaneOperationRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_control_plane_operation_global_row"):
        raise RuntimeError(
            "Global control-plane operations are unsupported by the active backend",
        )
    row = backend.load_control_plane_operation_global_row(op_id)
    if row is None:
        return None
    return mappers.control_plane_op_row_to_record(row)


# ---------------------------------------------------------------------------
# FlowExecution
# ---------------------------------------------------------------------------


def save_flow_execution(story_dir: Path, record: FlowExecution) -> None:
    row = mappers.flow_execution_to_row(record)
    _backend_module().save_flow_execution_row(story_dir, row)


def load_flow_execution(story_dir: Path) -> FlowExecution | None:
    row = _backend_module().load_flow_execution_row(story_dir)
    if row is None:
        return None
    return mappers.flow_execution_row_to_record(row)


def load_flow_execution_global(
    project_key: str,
    story_id: str,
) -> FlowExecution | None:
    backend = _backend_module()
    if not hasattr(backend, "load_flow_execution_global_row"):
        raise RuntimeError(
            "Global flow-execution reads are unsupported by the active backend",
        )
    row = backend.load_flow_execution_global_row(project_key, story_id)
    if row is None:
        return None
    return mappers.flow_execution_row_to_record(row)


# ---------------------------------------------------------------------------
# NodeExecutionLedger
# ---------------------------------------------------------------------------


def save_node_execution_ledger(story_dir: Path, record: NodeExecutionLedger) -> None:
    row = mappers.node_ledger_to_row(record)
    _backend_module().save_node_execution_ledger_row(story_dir, row)


def load_node_execution_ledger(
    story_dir: Path,
    flow_id: str,
    node_id: str,
) -> NodeExecutionLedger | None:
    row = _backend_module().load_node_execution_ledger_row(story_dir, flow_id, node_id)
    if row is None:
        return None
    return mappers.node_ledger_row_to_record(row)


# ---------------------------------------------------------------------------
# OverrideRecord
# ---------------------------------------------------------------------------


def save_override_record(story_dir: Path, record: OverrideRecord) -> None:
    row = mappers.override_record_to_row(record)
    _backend_module().save_override_record_row(story_dir, row)


def load_override_records(story_dir: Path) -> list[OverrideRecord]:
    rows = _backend_module().load_override_record_rows(story_dir)
    return [mappers.override_row_to_record(row) for row in rows]


# ---------------------------------------------------------------------------
# StoryMetricsRecord
# ---------------------------------------------------------------------------


def upsert_story_metrics(story_dir: Path, metrics: StoryMetricsRecord) -> None:
    row = mappers.story_metrics_to_row(metrics)
    _backend_module().upsert_story_metrics_row(story_dir, row)


def load_story_metrics(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
) -> list[StoryMetricsRecord]:
    rows = _backend_module().load_story_metrics_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
    )
    return [mappers.story_metrics_row_to_record(row) for row in rows]


def load_story_metrics_for_scope(
    scope: RuntimeStateScope,
) -> list[StoryMetricsRecord]:
    return load_story_metrics(
        scope.story_dir,
        project_key=scope.project_key,
        story_id=scope.story_id,
        run_id=scope.run_id,
    )


def load_latest_story_metrics_global(
    project_key: str,
    story_id: str,
    store_dir: Path | None = None,
) -> StoryMetricsRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_latest_story_metrics_global_row"):
        raise RuntimeError(
            "Global story-metrics reads are unsupported by the active backend",
        )
    row = backend.load_latest_story_metrics_global_row(store_dir, project_key, story_id)
    if row is None:
        return None
    return mappers.story_metrics_row_to_record(row)


# ---------------------------------------------------------------------------
# QA layer artifacts + verify decision
# ---------------------------------------------------------------------------


def record_layer_artifacts(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Serialize QA layer results and persist projection + FK-69 rows.

    Mapper converts BC-typed ``LayerResult`` objects to plain dicts;
    driver performs only SQL and filesystem I/O. ``artifact_envelopes``
    writes are owned by ``verify_system.artifacts`` — this facade does
    not know about ArtifactManager (no state_backend -> verify_system
    import).
    """
    from datetime import datetime

    from agentkit.boundary.shared.time import now_iso
    from agentkit.core_types.qa_artifact_names import LAYER_ARTIFACT_FILES

    # Need flow_row for FK-69 QA materialization (Postgres-specific)
    flow_row = _backend_module().load_flow_execution_row(story_dir)

    layer_payload_rows: list[dict[str, object]] = []
    for layer_result in layer_results:
        artifact_name = LAYER_ARTIFACT_FILES.get(layer_result.layer)
        if artifact_name is None:
            continue
        payload = mappers.serialize_layer_result_to_dict(
            layer_result,
            attempt_nr=attempt_nr,
        )
        producer_component = mappers.get_producer_component_for_layer(layer_result.layer)
        recorded_at = datetime.fromisoformat(now_iso())

        stage_row: dict[str, object] | None = None
        finding_rows: list[dict[str, object]] = []
        if flow_row is not None:
            stage_row = mappers.build_qa_stage_result_row(
                flow_row,
                layer_result,
                attempt_no=attempt_nr,
                artifact_id="",  # placeholder; driver replaces with real artifact_id
                recorded_at=recorded_at,
            )
            finding_rows = mappers.build_qa_finding_rows(
                flow_row,
                layer_result,
                attempt_no=attempt_nr,
                artifact_id="",  # placeholder
                recorded_at=recorded_at,
            )

        layer_payload_rows.append(
            {
                "layer": layer_result.layer,
                "artifact_name": artifact_name,
                "producer_component": producer_component,
                "payload": payload,
                "passed": layer_result.passed,
                "recorded_at": recorded_at.isoformat(),
                "stage_row": stage_row,
                "finding_rows": finding_rows,
            }
        )

    return cast(
        "tuple[str, ...]",
        _backend_module().persist_layer_artifact_rows(
            story_dir,
            flow_row=flow_row,
            layer_payload_rows=layer_payload_rows,
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
    """Serialize a verify decision and persist via driver."""

    canonical_payload = mappers.build_verify_decision_dict(
        decision,
        attempt_nr=attempt_nr,
    )
    flow_row = _backend_module().load_flow_execution_row(story_dir)
    return cast(
        "tuple[str, ...]",
        _backend_module().persist_verify_decision_row(
            story_dir,
            flow_row=flow_row,
            decision_row={
                "status": decision.status,
                "passed": decision.passed,
                "summary": decision.summary,
            },
            canonical_payload=canonical_payload,
            attempt_nr=attempt_nr,
            projection_dir=projection_dir,
        ),
    )


def load_latest_verify_decision(
    story_dir: Path,
) -> JsonRecord | None:
    return _cast_json_record(_backend_module().load_latest_verify_decision_payload(story_dir))


def load_latest_verify_decision_for_scope(
    scope: RuntimeStateScope,
) -> JsonRecord | None:
    return _cast_json_record(
        _backend_module().load_latest_verify_decision_payload_for_scope(scope),
    )


def read_latest_verify_decision_record(
    story_dir: Path,
) -> JsonRecord | None:
    return load_latest_verify_decision(story_dir)


# ---------------------------------------------------------------------------
# Artifact records (raw JSON payload reads)
# ---------------------------------------------------------------------------


def load_artifact_record(
    story_dir: Path,
    artifact_kind: str,
) -> JsonRecord | None:
    return _cast_json_record(
        _backend_module().load_artifact_record_payload(story_dir, artifact_kind),
    )


def load_artifact_record_for_scope(
    scope: RuntimeStateScope,
    artifact_kind: str,
) -> JsonRecord | None:
    return _cast_json_record(
        _backend_module().load_artifact_record_payload_for_scope(scope, artifact_kind),
    )


def read_artifact_record(
    story_dir: Path,
    artifact_kind: str,
) -> JsonRecord | None:
    return load_artifact_record(story_dir, artifact_kind)


# ---------------------------------------------------------------------------
# Closure report
# ---------------------------------------------------------------------------


def record_closure_report(
    story_dir: Path,
    report: ExecutionReport,
    *,
    projection_dir: Path | None = None,
) -> Path:
    flow_row = _backend_module().load_flow_execution_row(story_dir)
    payload = report.to_dict()
    return cast(
        "Path",
        _backend_module().persist_closure_report_row(
            story_dir,
            flow_row=flow_row,
            report_row={
                "story_id": getattr(report, "story_id", story_dir.name),
                "status": report.status,
                "payload": payload,
            },
            projection_dir=projection_dir,
        ),
    )


# ---------------------------------------------------------------------------
# QAStageResultRecord / QAFindingRecord
# ---------------------------------------------------------------------------


def load_qa_stage_results(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAStageResultRecord]:
    rows = _backend_module().load_qa_stage_result_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        attempt_no=attempt_no,
        stage_id=stage_id,
    )
    return [mappers.qa_stage_result_row_to_record(row) for row in rows]


def load_qa_stage_results_for_scope(
    scope: RuntimeStateScope,
    *,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAStageResultRecord]:
    return load_qa_stage_results(
        scope.story_dir,
        project_key=scope.project_key,
        story_id=scope.story_id,
        run_id=scope.run_id,
        attempt_no=attempt_no,
        stage_id=stage_id,
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
    rows = _backend_module().load_qa_finding_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        attempt_no=attempt_no,
        stage_id=stage_id,
    )
    return [mappers.qa_finding_row_to_record(row) for row in rows]


def load_qa_findings_for_scope(
    scope: RuntimeStateScope,
    *,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAFindingRecord]:
    return load_qa_findings(
        scope.story_dir,
        project_key=scope.project_key,
        story_id=scope.story_id,
        run_id=scope.run_id,
        attempt_no=attempt_no,
        stage_id=stage_id,
    )


# ---------------------------------------------------------------------------
# Backend predicate helpers
# ---------------------------------------------------------------------------


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
    return (
        isinstance(status, str)
        and bool(payload.get("passed"))
        and status == "PASS"
    )


def backend_verify_decision_passed_for_scope(scope: RuntimeStateScope) -> bool:
    return backend_verify_decision_passed(scope.story_dir)
