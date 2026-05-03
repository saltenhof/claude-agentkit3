"""BC-Record <-> dict-row mapper layer for state_backend drivers.

All conversions between typed BC-Records and raw dict rows live here.
Drivers (postgres_store, sqlite_store) receive and return only dicts;
this module is the single point of contact between BC types and the
persistence layer.

Projection helpers that previously lived in BC-A modules (qa.policy_engine.projections,
verify_system.qa_read_models) are also orchestrated here so that drivers
do not need to import BC-A modules directly.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agentkit.exceptions import CorruptStateError

if TYPE_CHECKING:
    from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.control_plane.records import (
        ControlPlaneOperationRecord,
        SessionRunBindingRecord,
    )
    from agentkit.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.phase_state_store.models import (
        FlowExecution,
        NodeExecutionLedger,
        OverrideRecord,
    )
    from agentkit.pipeline_engine.phase_executor.records import AttemptRecord
    from agentkit.project_management.entities import Project
    from agentkit.qa.policy_engine.engine import VerifyDecision
    from agentkit.qa.protocols import LayerResult
    from agentkit.story_context_manager.models import (
        PhaseSnapshot,
        PhaseState,
        StoryContext,
    )
    from agentkit.telemetry.contract.records import ExecutionEventRecord
    from agentkit.verify_system.stage_registry.records import (
        QAFindingRecord,
        QAStageResultRecord,
    )

_JsonRecord = dict[str, object]
_OptionalString = str | None

# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def dump_json(data: object) -> str:
    """Serialize data to a canonical JSON string."""

    return json.dumps(data, sort_keys=True, default=str)


def load_json(data: str | None, default: Any) -> Any:
    """Deserialize a JSON string, returning *default* if *data* is None."""

    if data is None:
        return default
    return json.loads(data)


def cast_json_record(value: object) -> _JsonRecord:
    """Cast an opaque value to ``dict[str, object]`` without allocation."""

    from typing import cast

    return cast("_JsonRecord", value)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


def project_to_row(project: Project) -> dict[str, Any]:
    """Convert a project entity to a DB-insertable row dict."""

    return {
        "key": project.key,
        "name": project.name,
        "story_id_prefix": project.story_id_prefix,
        "configuration_json": dump_json(project.configuration.model_dump(mode="json")),
        "archived_at": (
            project.archived_at.isoformat() if project.archived_at is not None else None
        ),
    }


def project_row_to_entity(row: dict[str, Any]) -> Project:
    """Convert a project DB row dict to a project entity."""

    from agentkit.project_management.entities import (
        Project as _Project,
    )
    from agentkit.project_management.entities import (
        ProjectConfiguration as _ProjectConfiguration,
    )

    configuration_raw = row.get("configuration_json", row.get("configuration"))
    configuration_payload = (
        json.loads(configuration_raw)
        if isinstance(configuration_raw, str)
        else configuration_raw
    )

    archived_at_raw = row.get("archived_at")
    archived_at = (
        datetime.fromisoformat(archived_at_raw)
        if isinstance(archived_at_raw, str)
        else archived_at_raw
    )

    return _Project(
        key=str(row["key"]),
        name=str(row["name"]),
        story_id_prefix=str(row["story_id_prefix"]),
        configuration=_ProjectConfiguration.model_validate(configuration_payload),
        archived_at=archived_at,
    )


# ---------------------------------------------------------------------------
# StoryContext
# ---------------------------------------------------------------------------


def story_context_to_row(ctx: StoryContext) -> dict[str, Any]:
    """Convert a ``StoryContext`` to a DB-insertable row dict."""

    return {
        "story_uuid": str(ctx.story_uuid),
        "project_key": ctx.project_key,
        "story_number": ctx.story_number,
        "story_id": ctx.story_id,
        "story_type": ctx.story_type.value,
        "execution_route": ctx.execution_route.value,
        "implementation_contract": (
            ctx.implementation_contract.value
            if ctx.implementation_contract is not None
            else None
        ),
        "issue_nr": ctx.issue_nr,
        "title": ctx.title,
        "payload_json": dump_json(ctx.model_dump(mode="json")),
    }


def story_context_payload_to_record(
    payload_json: str,
    db_label: str = "unknown",
) -> StoryContext:
    """Deserialize a ``StoryContext`` from its JSON payload."""

    from agentkit.story_context_manager.models import StoryContext as _StoryContext

    try:
        return _StoryContext.model_validate(json.loads(payload_json))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            f"story_contexts payload is invalid in {db_label}: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# PhaseState
# ---------------------------------------------------------------------------


def phase_state_to_row(state: PhaseState) -> dict[str, Any]:
    """Convert a ``PhaseState`` to a DB-insertable row dict."""

    return {
        "story_id": state.story_id,
        "phase": state.phase,
        "status": state.status.value,
        "paused_reason": state.paused_reason,
        "review_round": state.review_round,
        "attempt_id": state.attempt_id,
        "errors_json": dump_json(state.errors),
        "payload_json": dump_json(state.model_dump(mode="json")),
    }


def phase_state_payload_to_record(
    payload_json: str,
    db_label: str = "unknown",
) -> PhaseState:
    """Deserialize a ``PhaseState`` from its JSON payload."""

    from agentkit.story_context_manager.models import PhaseState as _PhaseState

    try:
        return _PhaseState.model_validate(json.loads(payload_json))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            f"phase_states payload is invalid in {db_label}: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# PhaseSnapshot
# ---------------------------------------------------------------------------


def phase_snapshot_to_row(snapshot: PhaseSnapshot) -> dict[str, Any]:
    """Convert a ``PhaseSnapshot`` to a DB-insertable row dict."""

    return {
        "story_id": snapshot.story_id,
        "phase": snapshot.phase,
        "status": snapshot.status.value,
        "completed_at": snapshot.completed_at.isoformat(),
        "payload_json": dump_json(snapshot.model_dump(mode="json")),
    }


def phase_snapshot_payload_to_record(
    payload_json: str,
    phase: str,
    db_label: str = "unknown",
) -> PhaseSnapshot:
    """Deserialize a ``PhaseSnapshot`` from its JSON payload."""

    from agentkit.story_context_manager.models import PhaseSnapshot as _PhaseSnapshot

    try:
        return _PhaseSnapshot.model_validate(json.loads(payload_json))
    except Exception as exc:  # noqa: BLE001
        raise CorruptStateError(
            f"phase_snapshots payload is invalid in {db_label} "
            f"for phase {phase!r}: {exc}",
        ) from exc


def phase_snapshot_completed(snapshot: PhaseSnapshot) -> bool:
    """Return True if the snapshot's status is COMPLETED."""

    from agentkit.story_context_manager.models import PhaseStatus as _PhaseStatus

    return snapshot.status == _PhaseStatus.COMPLETED


# ---------------------------------------------------------------------------
# AttemptRecord
# ---------------------------------------------------------------------------


def attempt_record_to_row(attempt: AttemptRecord) -> dict[str, Any]:
    """Convert an ``AttemptRecord`` to a DB-insertable row dict."""

    return {
        "phase": attempt.phase,
        "attempt_id": attempt.attempt_id,
        "entered_at": attempt.entered_at.isoformat(),
        "exit_status": attempt.exit_status.value if attempt.exit_status else None,
        "outcome": attempt.outcome,
        "yield_status": attempt.yield_status,
        "resume_trigger": attempt.resume_trigger,
        "guard_evaluations_json": dump_json(list(attempt.guard_evaluations)),
        "artifacts_json": dump_json(list(attempt.artifacts_produced)),
    }


def attempt_row_to_record(row: dict[str, Any]) -> AttemptRecord:
    """Convert a DB row dict to an ``AttemptRecord``."""

    from datetime import datetime
    from typing import cast

    from agentkit.pipeline_engine.phase_executor.records import (
        AttemptRecord as _AttemptRecord,
    )
    from agentkit.story_context_manager.models import PhaseStatus as _PhaseStatus

    return _AttemptRecord(
        attempt_id=str(row["attempt_id"]),
        phase=str(row["phase"]),
        entered_at=datetime.fromisoformat(str(row["entered_at"])),
        exit_status=(
            _PhaseStatus(str(row["exit_status"]))
            if row["exit_status"] is not None
            else None
        ),
        guard_evaluations=tuple(
            cast(
                "list[dict[str, object]]",
                load_json(str(row["guard_evaluations_json"]), []),
            )
        ),
        artifacts_produced=tuple(
            str(item)
            for item in cast(
                "list[object]",
                load_json(str(row["artifacts_json"]), []),
            )
        ),
        outcome=str(row["outcome"]) if row["outcome"] is not None else None,
        yield_status=(
            str(row["yield_status"]) if row["yield_status"] is not None else None
        ),
        resume_trigger=(
            str(row["resume_trigger"]) if row["resume_trigger"] is not None else None
        ),
    )


# ---------------------------------------------------------------------------
# FlowExecution
# ---------------------------------------------------------------------------


def flow_execution_to_row(record: FlowExecution) -> dict[str, Any]:
    """Convert a ``FlowExecution`` to a DB-insertable row dict."""

    return {
        "story_id": record.story_id,
        "project_key": record.project_key,
        "run_id": record.run_id,
        "flow_id": record.flow_id,
        "level": record.level,
        "owner": record.owner,
        "parent_flow_id": record.parent_flow_id,
        "status": record.status,
        "current_node_id": record.current_node_id,
        "attempt_no": record.attempt_no,
        "started_at": record.started_at.isoformat(),
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
    }


def flow_execution_row_to_record(row: dict[str, Any]) -> FlowExecution:
    """Convert a DB row dict to a ``FlowExecution``."""

    from datetime import datetime

    from agentkit.phase_state_store.models import FlowExecution as _FlowExecution

    return _FlowExecution(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        flow_id=str(row["flow_id"]),
        level=str(row["level"]),
        owner=str(row["owner"]),
        parent_flow_id=(
            str(row["parent_flow_id"]) if row["parent_flow_id"] is not None else None
        ),
        status=str(row["status"]),
        current_node_id=(
            str(row["current_node_id"]) if row["current_node_id"] is not None else None
        ),
        attempt_no=int(row["attempt_no"]),
        started_at=datetime.fromisoformat(str(row["started_at"])),
        finished_at=(
            datetime.fromisoformat(str(row["finished_at"]))
            if row["finished_at"] is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# NodeExecutionLedger
# ---------------------------------------------------------------------------


def node_ledger_to_row(record: NodeExecutionLedger) -> dict[str, Any]:
    """Convert a ``NodeExecutionLedger`` to a DB-insertable row dict."""

    return {
        "story_id": record.story_id,
        "flow_id": record.flow_id,
        "node_id": record.node_id,
        "project_key": record.project_key,
        "run_id": record.run_id,
        "execution_count": record.execution_count,
        "success_count": record.success_count,
        "last_outcome": record.last_outcome,
        "last_attempt_no": record.last_attempt_no,
        "last_executed_at": (
            record.last_executed_at.isoformat()
            if record.last_executed_at is not None
            else None
        ),
    }


def node_ledger_row_to_record(row: dict[str, Any]) -> NodeExecutionLedger:
    """Convert a DB row dict to a ``NodeExecutionLedger``."""

    from datetime import datetime

    from agentkit.phase_state_store.models import (
        NodeExecutionLedger as _NodeExecutionLedger,
    )

    return _NodeExecutionLedger(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        flow_id=str(row["flow_id"]),
        node_id=str(row["node_id"]),
        execution_count=int(row["execution_count"]),
        success_count=int(row["success_count"]),
        last_outcome=str(row["last_outcome"]) if row["last_outcome"] else None,
        last_attempt_no=(
            int(row["last_attempt_no"])
            if row["last_attempt_no"] is not None
            else None
        ),
        last_executed_at=(
            datetime.fromisoformat(str(row["last_executed_at"]))
            if row["last_executed_at"] is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# OverrideRecord
# ---------------------------------------------------------------------------


def override_record_to_row(record: OverrideRecord) -> dict[str, Any]:
    """Convert an ``OverrideRecord`` to a DB-insertable row dict."""

    return {
        "override_id": record.override_id,
        "story_id": record.story_id,
        "project_key": record.project_key,
        "run_id": record.run_id,
        "flow_id": record.flow_id,
        "target_node_id": record.target_node_id,
        "override_type": record.override_type,
        "actor_type": record.actor_type,
        "actor_id": record.actor_id,
        "reason": record.reason,
        "created_at": record.created_at.isoformat(),
        "consumed_at": record.consumed_at.isoformat() if record.consumed_at else None,
    }


def override_row_to_record(row: dict[str, Any]) -> OverrideRecord:
    """Convert a DB row dict to an ``OverrideRecord``."""

    from datetime import datetime

    from agentkit.phase_state_store.models import OverrideRecord as _OverrideRecord

    return _OverrideRecord(
        override_id=str(row["override_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        flow_id=str(row["flow_id"]),
        target_node_id=(
            str(row["target_node_id"]) if row["target_node_id"] is not None else None
        ),
        override_type=str(row["override_type"]),
        actor_type=str(row["actor_type"]),
        actor_id=str(row["actor_id"]),
        reason=str(row["reason"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        consumed_at=(
            datetime.fromisoformat(str(row["consumed_at"]))
            if row["consumed_at"] is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# StoryMetricsRecord
# ---------------------------------------------------------------------------


def story_metrics_to_row(metrics: StoryMetricsRecord) -> dict[str, Any]:
    """Convert a ``StoryMetricsRecord`` to a DB-insertable row dict."""

    return {
        "project_key": metrics.project_key,
        "story_id": metrics.story_id,
        "run_id": metrics.run_id,
        "story_type": metrics.story_type,
        "story_size": metrics.story_size,
        "mode": metrics.mode,
        "processing_time_min": metrics.processing_time_min,
        "qa_rounds": metrics.qa_rounds,
        "increments": metrics.increments,
        "final_status": metrics.final_status,
        "completed_at": metrics.completed_at,
        "adversarial_findings": metrics.adversarial_findings,
        "adversarial_tests_created": metrics.adversarial_tests_created,
        "files_changed": metrics.files_changed,
        "agentkit_version": metrics.agentkit_version,
        "agentkit_commit": metrics.agentkit_commit,
        "config_version": metrics.config_version,
        "llm_roles_json": dump_json(list(metrics.llm_roles)),
    }


def story_metrics_row_to_record(row: dict[str, Any]) -> StoryMetricsRecord:
    """Convert a DB row dict to a ``StoryMetricsRecord``."""

    from agentkit.closure.post_merge_finalization.records import (
        StoryMetricsRecord as _StoryMetricsRecord,
    )

    llm_roles = load_json(str(row["llm_roles_json"]), [])
    return _StoryMetricsRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        story_type=str(row["story_type"]),
        story_size=str(row["story_size"]),
        mode=str(row["mode"]),
        processing_time_min=float(row["processing_time_min"]),
        qa_rounds=int(row["qa_rounds"]),
        increments=int(row["increments"]),
        final_status=str(row["final_status"]),
        completed_at=str(row["completed_at"]),
        adversarial_findings=(
            int(row["adversarial_findings"])
            if row["adversarial_findings"] is not None
            else None
        ),
        adversarial_tests_created=(
            int(row["adversarial_tests_created"])
            if row["adversarial_tests_created"] is not None
            else None
        ),
        files_changed=(
            int(row["files_changed"]) if row["files_changed"] is not None else None
        ),
        agentkit_version=(
            str(row["agentkit_version"])
            if row["agentkit_version"] is not None
            else None
        ),
        agentkit_commit=(
            str(row["agentkit_commit"]) if row["agentkit_commit"] is not None else None
        ),
        config_version=(
            str(row["config_version"]) if row["config_version"] is not None else None
        ),
        llm_roles=tuple(str(role) for role in llm_roles if isinstance(role, str)),
    )


# ---------------------------------------------------------------------------
# ExecutionEventRecord
# ---------------------------------------------------------------------------


def execution_event_to_row(event: ExecutionEventRecord) -> dict[str, Any]:
    """Convert an ``ExecutionEventRecord`` to a DB-insertable row dict."""

    return {
        "project_key": event.project_key,
        "story_id": event.story_id,
        "run_id": event.run_id,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at.isoformat(),
        "source_component": event.source_component,
        "severity": event.severity,
        "phase": event.phase,
        "flow_id": event.flow_id,
        "node_id": event.node_id,
        "payload_json": dump_json(event.payload),
    }


def execution_event_row_to_record(row: dict[str, Any]) -> ExecutionEventRecord:
    """Convert a DB row dict to an ``ExecutionEventRecord``."""

    from datetime import datetime

    from agentkit.telemetry.contract.records import (
        ExecutionEventRecord as _ExecutionEventRecord,
    )

    return _ExecutionEventRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        event_id=str(row["event_id"]),
        event_type=str(row["event_type"]),
        occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
        source_component=str(row["source_component"]),
        severity=str(row["severity"]),
        phase=str(row["phase"]) if row["phase"] is not None else None,
        flow_id=str(row["flow_id"]) if row["flow_id"] is not None else None,
        node_id=str(row["node_id"]) if row["node_id"] is not None else None,
        payload=cast_json_record(load_json(str(row["payload_json"]), {})),
    )


# ---------------------------------------------------------------------------
# StoryExecutionLockRecord
# ---------------------------------------------------------------------------


def execution_lock_to_row(record: StoryExecutionLockRecord) -> dict[str, Any]:
    """Convert a ``StoryExecutionLockRecord`` to a DB-insertable row dict."""

    return {
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "lock_type": record.lock_type,
        "status": record.status,
        "worktree_roots_json": dump_json(list(record.worktree_roots)),
        "binding_version": record.binding_version,
        "activated_at": record.activated_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "deactivated_at": (
            record.deactivated_at.isoformat()
            if record.deactivated_at is not None
            else None
        ),
    }


def execution_lock_row_to_record(row: dict[str, Any]) -> StoryExecutionLockRecord:
    """Convert a DB row dict to a ``StoryExecutionLockRecord``."""

    from datetime import datetime

    from agentkit.governance.guard_system.records import (
        StoryExecutionLockRecord as _StoryExecutionLockRecord,
    )

    deactivated_at_raw = row["deactivated_at"]
    return _StoryExecutionLockRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        lock_type=str(row["lock_type"]),
        status=str(row["status"]),
        worktree_roots=tuple(load_json(row["worktree_roots_json"], [])),
        binding_version=str(row["binding_version"]),
        activated_at=datetime.fromisoformat(str(row["activated_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        deactivated_at=(
            datetime.fromisoformat(str(deactivated_at_raw))
            if deactivated_at_raw is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# SessionRunBindingRecord
# ---------------------------------------------------------------------------


def session_binding_to_row(record: SessionRunBindingRecord) -> dict[str, Any]:
    """Convert a ``SessionRunBindingRecord`` to a DB-insertable row dict."""

    return {
        "session_id": record.session_id,
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "principal_type": record.principal_type,
        "worktree_roots_json": dump_json(list(record.worktree_roots)),
        "binding_version": record.binding_version,
        "updated_at": record.updated_at.isoformat(),
    }


def session_binding_row_to_record(row: dict[str, Any]) -> SessionRunBindingRecord:
    """Convert a DB row dict to a ``SessionRunBindingRecord``."""

    from datetime import datetime

    from agentkit.control_plane.records import (
        SessionRunBindingRecord as _SessionRunBindingRecord,
    )

    return _SessionRunBindingRecord(
        session_id=str(row["session_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        principal_type=str(row["principal_type"]),
        worktree_roots=tuple(load_json(row["worktree_roots_json"], [])),
        binding_version=str(row["binding_version"]),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


# ---------------------------------------------------------------------------
# ControlPlaneOperationRecord
# ---------------------------------------------------------------------------


def control_plane_op_to_row(record: ControlPlaneOperationRecord) -> dict[str, Any]:
    """Convert a ``ControlPlaneOperationRecord`` to a DB-insertable row dict."""

    return {
        "op_id": record.op_id,
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "session_id": record.session_id,
        "operation_kind": record.operation_kind,
        "phase": record.phase,
        "status": record.status,
        "response_json": dump_json(record.response_payload),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def control_plane_op_row_to_record(
    row: dict[str, Any],
) -> ControlPlaneOperationRecord:
    """Convert a DB row dict to a ``ControlPlaneOperationRecord``."""

    from datetime import datetime
    from typing import cast

    from agentkit.control_plane.records import (
        ControlPlaneOperationRecord as _ControlPlaneOperationRecord,
    )

    return _ControlPlaneOperationRecord(
        op_id=str(row["op_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=cast("_OptionalString", row["run_id"]),
        session_id=cast("_OptionalString", row["session_id"]),
        operation_kind=str(row["operation_kind"]),
        phase=cast("_OptionalString", row["phase"]),
        status=str(row["status"]),
        response_payload=cast_json_record(load_json(row["response_json"], {})),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


# ---------------------------------------------------------------------------
# QAStageResultRecord
# ---------------------------------------------------------------------------


def qa_stage_result_row_to_record(row: dict[str, Any]) -> QAStageResultRecord:
    """Convert a DB row dict to a ``QAStageResultRecord``."""

    from datetime import datetime

    from agentkit.verify_system.stage_registry.records import (
        QAStageResultRecord as _QAStageResultRecord,
    )

    return _QAStageResultRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        attempt_no=int(row["attempt_no"]),
        stage_id=str(row["stage_id"]),
        layer=str(row["layer"]),
        producer_component=str(row["producer_component"]),
        status=str(row["status"]),
        blocking=bool(row["blocking"]),
        total_checks=int(row["total_checks"]),
        failed_checks=int(row["failed_checks"]),
        warning_checks=int(row["warning_checks"]),
        artifact_id=str(row["artifact_id"]),
        recorded_at=datetime.fromisoformat(str(row["recorded_at"])),
    )


# ---------------------------------------------------------------------------
# QAFindingRecord
# ---------------------------------------------------------------------------


def qa_finding_row_to_record(row: dict[str, Any]) -> QAFindingRecord:
    """Convert a DB row dict to a ``QAFindingRecord``."""

    from datetime import datetime

    from agentkit.verify_system.stage_registry.records import (
        QAFindingRecord as _QAFindingRecord,
    )

    return _QAFindingRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        attempt_no=int(row["attempt_no"]),
        stage_id=str(row["stage_id"]),
        finding_id=str(row["finding_id"]),
        check_id=str(row["check_id"]),
        status=str(row["status"]),
        severity=str(row["severity"]),
        blocking=bool(row["blocking"]),
        source_component=str(row["source_component"]),
        artifact_id=str(row["artifact_id"]),
        occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
        category=str(row["category"]) if row["category"] is not None else None,
        reason=str(row["reason"]) if row["reason"] is not None else None,
        description=(
            str(row["description"]) if row["description"] is not None else None
        ),
        detail=str(row["detail"]) if row["detail"] is not None else None,
        metadata=cast_json_record(load_json(str(row["metadata_json"]), {})),
    )


# ---------------------------------------------------------------------------
# QA layer artifact / verify decision serialization helpers
# (moved from BC-A modules so drivers need not import them directly)
# ---------------------------------------------------------------------------


def serialize_layer_result_to_dict(
    layer_result: LayerResult,
    *,
    attempt_nr: int,
) -> dict[str, object]:
    """Serialize a ``LayerResult`` to the canonical artifact payload dict."""

    from agentkit.qa.policy_engine.projections import (
        serialize_layer_result as _serialize_layer_result,
    )

    return _serialize_layer_result(layer_result, attempt_nr=attempt_nr)


def build_verify_decision_dict(
    decision: VerifyDecision,
    *,
    attempt_nr: int,
) -> dict[str, object]:
    """Build the canonical verify-decision artifact dict."""

    from agentkit.qa.policy_engine.projections import (
        build_verify_decision_artifact as _build_verify_decision_artifact,
    )

    return _build_verify_decision_artifact(decision, attempt_nr=attempt_nr)


def get_producer_component_for_layer(layer: str) -> str:
    """Return the canonical producer component name for a QA layer."""

    from agentkit.verify_system.qa_read_models import (
        producer_component_for_layer as _producer_component_for_layer,
    )

    return _producer_component_for_layer(layer)


def build_qa_stage_result_row(
    flow_row: dict[str, Any],
    layer_result: LayerResult,
    *,
    attempt_no: int,
    artifact_id: str,
    recorded_at: datetime,
) -> dict[str, Any]:
    """Build a ``qa_stage_results`` insert-row from a flow row and layer result."""

    from agentkit.verify_system.qa_read_models import (
        build_qa_stage_result as _build_qa_stage_result,
    )

    flow = flow_execution_row_to_record(flow_row)
    stage_record = _build_qa_stage_result(
        flow,
        layer_result,
        attempt_no=attempt_no,
        artifact_id=artifact_id,
        recorded_at=recorded_at,
    )
    return {
        "project_key": stage_record.project_key,
        "story_id": stage_record.story_id,
        "run_id": stage_record.run_id,
        "attempt_no": stage_record.attempt_no,
        "stage_id": stage_record.stage_id,
        "layer": stage_record.layer,
        "producer_component": stage_record.producer_component,
        "status": stage_record.status,
        "blocking": 1 if stage_record.blocking else 0,
        "total_checks": stage_record.total_checks,
        "failed_checks": stage_record.failed_checks,
        "warning_checks": stage_record.warning_checks,
        "artifact_id": stage_record.artifact_id,
        "recorded_at": stage_record.recorded_at.isoformat(),
    }


def build_qa_finding_rows(
    flow_row: dict[str, Any],
    layer_result: LayerResult,
    *,
    attempt_no: int,
    artifact_id: str,
    recorded_at: datetime,
) -> list[dict[str, Any]]:
    """Build ``qa_findings`` insert-rows from a flow row and layer result."""

    from agentkit.verify_system.qa_read_models import (
        build_qa_findings as _build_qa_findings,
    )

    flow = flow_execution_row_to_record(flow_row)
    finding_records = _build_qa_findings(
        flow,
        layer_result,
        attempt_no=attempt_no,
        artifact_id=artifact_id,
        recorded_at=recorded_at,
    )
    return [
        {
            "project_key": r.project_key,
            "story_id": r.story_id,
            "run_id": r.run_id,
            "attempt_no": r.attempt_no,
            "stage_id": r.stage_id,
            "finding_id": r.finding_id,
            "check_id": r.check_id,
            "status": r.status,
            "severity": r.severity,
            "blocking": 1 if r.blocking else 0,
            "source_component": r.source_component,
            "artifact_id": r.artifact_id,
            "occurred_at": r.occurred_at.isoformat(),
            "category": r.category,
            "reason": r.reason,
            "description": r.description,
            "detail": r.detail,
            "metadata_json": dump_json(r.metadata),
        }
        for r in finding_records
    ]
