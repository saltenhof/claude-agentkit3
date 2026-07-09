"""Telemetry and story-metrics row mappers."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ._common import cast_json_record, dump_json, load_json

if TYPE_CHECKING:
    from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord



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

    from agentkit.backend.closure.post_merge_finalization.records import (
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


    from agentkit.backend.telemetry.contract.records import (
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
