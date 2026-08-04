"""Test support for the productive atomic QA-layer persistence boundary."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.artifacts import (
    ArtifactEnvelope,
    EnvelopeStatus,
    Producer,
    ProducerId,
)
from agentkit.backend.bootstrap.composition_artifacts import build_artifact_manager
from agentkit.backend.bootstrap.composition_state import build_projection_accessor
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.core_types.qa_artifact_names import STABILITY_GATE_PRODUCER
from agentkit.backend.state_backend.governance_runtime_store import (
    bind_ownership_fence_scope,
)
from agentkit.backend.state_backend.pipeline_runtime_store import load_flow_execution
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    _sqlite_connect_qa,
)
from agentkit.backend.verify_system import _artifact_specs
from agentkit.backend.verify_system.check_outcome_emitter import CheckOutcomeEmitter
from agentkit.backend.verify_system.policy_engine.projections import serialize_layer_result
from agentkit.backend.verify_system.register import _VERIFY_PRODUCERS

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.artifacts import ArtifactReference
    from agentkit.backend.verify_system.protocols import LayerResult
    from agentkit.backend.verify_system.stage_registry.records import (
        QACheckOutcomeRecord,
        QAFindingRecord,
        QAStageResultRecord,
    )
    from agentkit.backend.verify_system.stage_registry.registry import StageRegistry


def record_qa_layer_artifacts(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    stage_registry: StageRegistry,
    attempt_nr: int,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Build outcomes and call the one productive Stage/Finding/Outcome batch."""
    flow = load_flow_execution(story_dir)
    if flow is None:
        raise ValueError("test QA batch requires a persisted FlowExecution")
    synthetic_check_ids: set[str] = set()
    for layer_result in layer_results:
        raw_check_ids = layer_result.metadata.get("executed_check_ids", ())
        if isinstance(raw_check_ids, (list, tuple)):
            synthetic_check_ids.update(
                check_id for check_id in raw_check_ids if isinstance(check_id, str)
            )
    test_stage_registry = replace(
        stage_registry,
        native_check_origin_refs={
            **stage_registry.native_check_origin_refs,
            **dict.fromkeys(synthetic_check_ids),
        },
    )
    check_outcomes = CheckOutcomeEmitter().build_batch(
        flow,
        layer_results,
        attempt_no=attempt_nr,
        stage_registry=test_stage_registry,
    )
    with bind_ownership_fence_scope(
        project_key=flow.project_key,
        story_id=flow.story_id,
        run_id=flow.run_id,
        owner_session_id=owner_session_id,
        expected_ownership_epoch=expected_ownership_epoch,
    ):
        artifact_references = write_qa_layer_envelopes(
            story_dir,
            layer_results=layer_results,
            stage_registry=test_stage_registry,
            attempt_nr=attempt_nr,
        )
    referenced_results = tuple(
        replace(
            result,
            artifact_reference=artifact_references[result.layer],
        )
        for result in layer_results
    )
    return build_projection_accessor(story_dir).record_qa_layer_artifacts(
        story_dir,
        layer_results=referenced_results,
        check_outcomes=check_outcomes,
        stage_registry=test_stage_registry,
        attempt_nr=attempt_nr,
        owner_session_id=owner_session_id,
        expected_ownership_epoch=expected_ownership_epoch,
        projection_dir=projection_dir,
    )


def write_qa_layer_envelopes(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    stage_registry: StageRegistry,
    attempt_nr: int,
) -> dict[str, ArtifactReference]:
    """Write the canonical envelopes required by the FK-69 test batch."""
    flow = load_flow_execution(story_dir)
    if flow is None:
        raise ValueError("test QA envelopes require a persisted FlowExecution")
    qa_producer_types = {
        name: producer_type
        for artifact_class, name, producer_type in _VERIFY_PRODUCERS
        if artifact_class is ArtifactClass.QA
    }
    artifact_stages = {
        spec.producer_name: spec.stage
        for spec in (
            *_artifact_specs.LAYER_1_ARTIFACTS,
            *_artifact_specs.LAYER_2_SPECS,
            *_artifact_specs.LAYER_3_ARTIFACTS,
            *_artifact_specs.SONARQUBE_GATE_ARTIFACTS,
            _artifact_specs.CONTEXT_SUFFICIENCY_ARTIFACT_SPEC,
        )
    }
    artifact_stages[STABILITY_GATE_PRODUCER] = "stability_gate"
    manager = build_artifact_manager(story_dir)
    recorded_at = datetime.now(UTC)
    references: dict[str, ArtifactReference] = {}
    for result in layer_results:
        producer_name = stage_registry.producer_for_result_name(result.layer)
        producer_type = qa_producer_types.get(producer_name)
        if producer_type is None:
            raise ValueError(f"unregistered QA test producer: {producer_name!r}")
        artifact_stage = artifact_stages.get(producer_name)
        if artifact_stage is None:
            raise ValueError(
                f"QA test producer has no layer artifact stage: {producer_name!r}"
            )
        envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id=flow.story_id,
            run_id=flow.run_id,
            stage=artifact_stage,
            attempt=attempt_nr,
            producer=Producer(
                type=producer_type,
                name=producer_name,
                id=ProducerId(f"{producer_name}-{flow.run_id}-{attempt_nr}"),
            ),
            started_at=recorded_at,
            finished_at=recorded_at,
            status=EnvelopeStatus.PASS if result.passed else EnvelopeStatus.FAIL,
            artifact_class=ArtifactClass.QA,
            payload=serialize_layer_result(result, attempt_nr=attempt_nr),
        )
        references[result.layer] = manager.write(envelope)
    return references


def seed_qa_stage_result(story_dir: Path, record: QAStageResultRecord) -> None:
    """Seed SQLite below the business boundary for repository read/purge tests."""
    with _sqlite_connect_qa(story_dir) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO qa_stage_results (
                project_key, story_id, run_id, attempt_no, stage_id, layer,
                producer_component, status, blocking, total_checks,
                failed_checks, warning_checks, artifact_id, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.project_key,
                record.story_id,
                record.run_id,
                record.attempt_no,
                record.stage_id,
                record.layer,
                record.producer_component,
                record.status,
                int(record.blocking),
                record.total_checks,
                record.failed_checks,
                record.warning_checks,
                record.artifact_id,
                record.recorded_at.isoformat(),
            ),
        )


def seed_qa_finding(story_dir: Path, record: QAFindingRecord) -> None:
    """Seed one finding for a SQLite read/purge test."""
    with _sqlite_connect_qa(story_dir) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO qa_findings (
                project_key, story_id, run_id, attempt_no, stage_id,
                finding_id, check_id, status, severity, blocking,
                source_component, artifact_id, occurred_at,
                category, reason, description, detail, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.project_key,
                record.story_id,
                record.run_id,
                record.attempt_no,
                record.stage_id,
                record.finding_id,
                record.check_id,
                record.status,
                record.severity,
                int(record.blocking),
                record.source_component,
                record.artifact_id,
                record.occurred_at.isoformat(),
                record.category,
                record.reason,
                record.description,
                record.detail,
                json.dumps(record.metadata, sort_keys=True),
            ),
        )


def seed_qa_check_outcome(story_dir: Path, record: QACheckOutcomeRecord) -> None:
    """Seed one outcome for a SQLite read/filter/purge test."""
    with _sqlite_connect_qa(story_dir) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO qa_check_outcomes (
                project_key, story_id, run_id, stage_id, attempt_no, check_id,
                outcome, occurred_at, check_proposal_ref, override_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.project_key,
                record.story_id,
                record.run_id,
                record.stage_id,
                record.attempt_no,
                record.check_id,
                str(record.outcome),
                record.occurred_at.isoformat(),
                record.check_proposal_ref,
                record.override_id,
            ),
        )


__all__ = [
    "record_qa_layer_artifacts",
    "seed_qa_check_outcome",
    "seed_qa_finding",
    "seed_qa_stage_result",
    "write_qa_layer_envelopes",
]
