"""Verify artifact and decision persistence store."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend.persistence_json_codec import (
    JsonRecord,
    _cast_json_record,
)
from agentkit.backend.state_backend.runtime_scope_resolver import resolve_runtime_scope
from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.state_backend.scope import RuntimeStateScope
    from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.backend.verify_system.protocols import LayerResult


def record_layer_artifacts(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    attempt_nr: int,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Serialize QA layer artifacts and persist them through the active backend."""
    from datetime import datetime

    from agentkit.backend.boundary.shared.time import now_iso
    from agentkit.backend.core_types.qa_artifact_names import LAYER_ARTIFACT_FILES
    from agentkit.backend.state_backend import persistence_mappers as mappers

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
        producer_component = mappers.get_producer_component_for_layer(
            layer_result.layer,
        )
        recorded_at = datetime.fromisoformat(now_iso())

        stage_row: dict[str, object] | None = None
        finding_rows: list[dict[str, object]] = []
        if flow_row is not None:
            stage_row = mappers.build_qa_stage_result_row(
                flow_row,
                layer_result,
                attempt_no=attempt_nr,
                artifact_id="",
                recorded_at=recorded_at,
            )
            finding_rows = mappers.build_qa_finding_rows(
                flow_row,
                layer_result,
                attempt_no=attempt_nr,
                artifact_id="",
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
            owner_session_id=owner_session_id,
            expected_ownership_epoch=expected_ownership_epoch,
            projection_dir=projection_dir,
        ),
    )


def record_verify_decision(
    story_dir: Path,
    *,
    decision: VerifyDecision,
    attempt_nr: int,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Serialize and persist one verify decision."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

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
            owner_session_id=owner_session_id,
            expected_ownership_epoch=expected_ownership_epoch,
            projection_dir=projection_dir,
        ),
    )


def load_latest_verify_decision(
    story_dir: Path,
) -> JsonRecord | None:
    """Load the latest verify decision payload for a story."""
    return _cast_json_record(
        _backend_module().load_latest_verify_decision_payload(story_dir),
    )


def load_latest_verify_decision_for_scope(
    scope: RuntimeStateScope,
) -> JsonRecord | None:
    """Load the latest verify decision payload for an explicit runtime scope."""
    return _cast_json_record(
        _backend_module().load_latest_verify_decision_payload_for_scope(scope),
    )


def read_latest_verify_decision_record(
    story_dir: Path,
) -> JsonRecord | None:
    """Compatibility alias for ``load_latest_verify_decision``."""
    return load_latest_verify_decision(story_dir)


def find_latest_qa_envelope(
    story_dir: Path,
    scope: RuntimeStateScope | None,
    stage: str,
) -> object | None:
    """Return the highest-attempt canonical QA artifact envelope for one stage."""
    from agentkit.backend.core_types import ArtifactClass
    from agentkit.backend.state_backend.artifact_envelope_mappers import (
        postgres_artifact_envelope_row_to_record,
        sqlite_artifact_envelope_row_to_record,
    )

    if scope is not None:
        story_id, run_id = scope.story_id, scope.run_id
    else:
        try:
            resolved = resolve_runtime_scope(story_dir)
        except CorruptStateError:
            return None
        story_id, run_id = resolved.story_id, resolved.run_id

    backend = _backend_module()
    row = backend.find_latest_artifact_envelope_row(
        story_dir,
        story_id=story_id,
        run_id=run_id,
        artifact_class=ArtifactClass.QA,
        stage=stage,
    )
    if row is None:
        return None
    if backend.__name__.endswith(".postgres_store"):
        return postgres_artifact_envelope_row_to_record(row)
    return sqlite_artifact_envelope_row_to_record(row)


def backend_has_structural_artifact(story_dir: Path) -> bool:
    """Return whether the story has a structural artifact payload."""
    record = _backend_module().load_artifact_record_payload(story_dir, "structural")
    return record is not None


def backend_has_structural_artifact_for_scope(scope: RuntimeStateScope) -> bool:
    """Return whether the scoped story has a structural artifact payload."""
    return backend_has_structural_artifact(scope.story_dir)


def backend_verify_decision_passed(story_dir: Path) -> bool:
    """Return whether the latest verify decision is a passing PASS decision."""
    payload = load_latest_verify_decision(story_dir)
    if payload is None:
        return False
    status = payload.get("status")
    return isinstance(status, str) and bool(payload.get("passed")) and status == "PASS"


def backend_verify_decision_passed_for_scope(scope: RuntimeStateScope) -> bool:
    """Return whether the scoped story has a passing latest verify decision."""
    return backend_verify_decision_passed(scope.story_dir)


def purge_decision_records(story_dir: Path, story_id: str) -> int:
    """Delete all verify decision rows for ``story_id``."""
    return int(_backend_module().purge_decision_records_row(story_dir, story_id))


__all__ = [
    "record_layer_artifacts",
    "record_verify_decision",
    "load_latest_verify_decision",
    "load_latest_verify_decision_for_scope",
    "read_latest_verify_decision_record",
    "find_latest_qa_envelope",
    "backend_has_structural_artifact",
    "backend_has_structural_artifact_for_scope",
    "backend_verify_decision_passed",
    "backend_verify_decision_passed_for_scope",
    "purge_decision_records",
]
