"""Verify-system row mappers and QA read-model projections."""


from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ._common import cast_json_record, dump_json, load_json
from ._runtime import flow_execution_row_to_record

if TYPE_CHECKING:
    from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.backend.verify_system.protocols import LayerResult
    from agentkit.backend.verify_system.stage_registry.records import (
        QAFindingRecord,
        QAStageResultRecord,
    )


def qa_stage_result_row_to_record(row: dict[str, Any]) -> QAStageResultRecord:
    """Convert a DB row dict to a ``QAStageResultRecord``."""


    from agentkit.backend.verify_system.stage_registry.records import (
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


def qa_finding_row_to_record(row: dict[str, Any]) -> QAFindingRecord:
    """Convert a DB row dict to a ``QAFindingRecord``."""


    from agentkit.backend.verify_system.stage_registry.records import (
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


def serialize_layer_result_to_dict(
    layer_result: LayerResult,
    *,
    attempt_nr: int,
) -> dict[str, object]:
    """Serialize a ``LayerResult`` to the canonical artifact payload dict."""

    from agentkit.backend.verify_system.policy_engine.projections import (
        serialize_layer_result as _serialize_layer_result,
    )

    return _serialize_layer_result(layer_result, attempt_nr=attempt_nr)


def build_verify_decision_dict(
    decision: VerifyDecision,
    *,
    attempt_nr: int,
) -> dict[str, object]:
    """Build the canonical verify-decision artifact dict."""

    from agentkit.backend.verify_system.policy_engine.projections import (
        build_verify_decision_artifact as _build_verify_decision_artifact,
    )

    return _build_verify_decision_artifact(decision, attempt_nr=attempt_nr)


def get_producer_component_for_layer(layer: str) -> str:
    """Return the canonical producer component name for a QA layer."""

    from agentkit.backend.verify_system.qa_read_models import (
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

    from agentkit.backend.verify_system.qa_read_models import (
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

    from agentkit.backend.verify_system.qa_read_models import (
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
