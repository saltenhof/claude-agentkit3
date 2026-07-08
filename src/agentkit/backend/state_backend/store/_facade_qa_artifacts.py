"""QA artifact, verify decision, closure report, and QA read facade operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend.store import mappers
from agentkit.backend.state_backend.store._facade_backend import (
    JsonRecord,
    _backend_module,
    _cast_json_record,
)
from agentkit.backend.state_backend.store._facade_runtime_scope import (
    resolve_runtime_scope,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.closure.execution_report.records import ExecutionReport
    from agentkit.backend.state_backend.scope import RuntimeStateScope
    from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.backend.verify_system.protocols import LayerResult
    from agentkit.backend.verify_system.stage_registry.records import (
        QAFindingRecord,
        QAStageResultRecord,
    )


def record_layer_artifacts(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    attempt_nr: int,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Serialize QA layer results and persist projection + FK-69 rows.

    Mapper converts BC-typed ``LayerResult`` objects to plain dicts;
    driver performs only SQL and filesystem I/O. ``artifact_envelopes``
    writes are owned by ``verify_system.artifacts`` — this facade does
    not know about ArtifactManager (no state_backend -> verify_system
    import).

    Args:
        owner_session_id: (AG3-144, FK-91 §91.1a Rule 15) The caller's
            early-captured active ``run_ownership_records.owner_session_id``
            (mirrors the AG3-142 regime-commit pattern). Re-verified at commit
            time, in the SAME transaction, under ``SELECT ... FOR UPDATE``.
        expected_ownership_epoch: The caller's early-captured
            ``ownership_epoch`` snapshot, re-verified the same way.

    Raises:
        OwnershipFenceViolationError: (AG3-142 reuse) When the story's active
            ownership record no longer admits this exact snapshot at commit
            time -- nothing written (no projection file, no QA rows).
    """
    from datetime import datetime

    from agentkit.backend.boundary.shared.time import now_iso
    from agentkit.backend.core_types.qa_artifact_names import LAYER_ARTIFACT_FILES

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
    """Serialize a verify decision and persist via driver.

    Args:
        owner_session_id: (AG3-144, FK-91 §91.1a Rule 15) The caller's
            early-captured active ``run_ownership_records.owner_session_id``.
            Re-verified at commit time under ``SELECT ... FOR UPDATE``.
        expected_ownership_epoch: The caller's early-captured
            ``ownership_epoch`` snapshot, re-verified the same way.

    Raises:
        OwnershipFenceViolationError: (AG3-142 reuse) When the story's active
            ownership record no longer admits this exact snapshot at commit
            time -- nothing written.
    """

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


def find_latest_qa_envelope(
    story_dir: Path,
    scope: RuntimeStateScope | None,
    stage: str,
) -> object | None:
    """Return the highest-attempt canonical QA ``ArtifactEnvelope`` for a stage.

    The canonical QA-artefact truth lives in ``artifact_envelopes``
    (``ArtifactClass.QA``); this resolves the latest envelope for one QA layer
    stage (e.g. ``qa-layer-structural`` / ``qa-policy-decision`` /
    ``qa-layer-adversarial``) so the IntegrityGate dimensions (FK-35 §35.2.4)
    can verify producer / status / payload depth against the real artefact.

    Args:
        story_dir: Story base directory (used to resolve the story_id/run_id
            when ``scope`` is ``None``).
        scope: Resolved runtime scope (narrows to one run_id when present).
        stage: The QA layer stage id.

    Returns:
        The latest :class:`ArtifactEnvelope` (typed ``object`` to keep the
        facade import-light), or ``None`` when absent.
    """
    from agentkit.backend.core_types import ArtifactClass
    from agentkit.backend.state_backend.store.artifact_repository import (
        StateBackendArtifactRepository,
    )

    if scope is not None:
        story_id, run_id = scope.story_id, scope.run_id
    else:
        try:
            resolved = resolve_runtime_scope(story_dir)
        except CorruptStateError:
            return None
        story_id, run_id = resolved.story_id, resolved.run_id
    repository = StateBackendArtifactRepository(story_dir)
    return repository.find_latest_envelope(
        story_id=story_id,
        run_id=run_id,
        artifact_class=ArtifactClass.QA,
        stage=stage,
    )


def find_prompt_audit_output_hashes(
    story_dir: Path,
    scope: RuntimeStateScope | None,
) -> frozenset[str]:
    """Return all prompt-audit ``output_sha256`` digests for the run scope.

    The canonical prompt-audit truth lives in ``artifact_envelopes``
    (``ArtifactClass.PROMPT_AUDIT``, FK-44 §44.6). Each record carries
    ``output_sha256`` -- the digest of the exact materialized prompt bytes,
    rendered from a manifest-pinned bundle template. The set of these digests is
    the FK-31 §31.7.4 Stage-3 baseline for the PromptIntegrityGuard: it is
    install-pinned, NOT spawn-controlled.

    Args:
        story_dir: Story base directory (used to resolve the story_id/run_id
            when ``scope`` is ``None``).
        scope: Resolved runtime scope (narrows to one run_id when present).

    Returns:
        The frozenset of all ``output_sha256`` digests for the (story, run)
        scope (empty when none materialized or the scope is unresolvable).
    """
    from agentkit.backend.state_backend.store.artifact_repository import (
        StateBackendArtifactRepository,
    )

    if scope is not None:
        story_id, run_id = scope.story_id, scope.run_id
    else:
        try:
            resolved = resolve_runtime_scope(story_dir)
        except CorruptStateError:
            return frozenset()
        story_id, run_id = resolved.story_id, resolved.run_id
    if not run_id:
        return frozenset()
    repository = StateBackendArtifactRepository(story_dir)
    return repository.find_prompt_audit_output_hashes(
        story_id=story_id,
        run_id=run_id,
    )


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


def record_closure_report(
    story_dir: Path,
    report: ExecutionReport,
    *,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> Path:
    """Persist the closure report and its export projection.

    Args:
        owner_session_id: (AG3-144, FK-91 §91.1a Rule 15) The caller's
            early-captured active ``run_ownership_records.owner_session_id``.
            Re-verified at commit time under ``SELECT ... FOR UPDATE``.
        expected_ownership_epoch: The caller's early-captured
            ``ownership_epoch`` snapshot, re-verified the same way.

    Raises:
        OwnershipFenceViolationError: (AG3-142 reuse) When the story's active
            ownership record no longer admits this exact snapshot at commit
            time -- nothing written.
    """
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
            owner_session_id=owner_session_id,
            expected_ownership_epoch=expected_ownership_epoch,
            projection_dir=projection_dir,
        ),
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


__all__ = [
    "record_layer_artifacts",
    "record_verify_decision",
    "load_latest_verify_decision",
    "load_latest_verify_decision_for_scope",
    "read_latest_verify_decision_record",
    "find_latest_qa_envelope",
    "find_prompt_audit_output_hashes",
    "load_artifact_record",
    "load_artifact_record_for_scope",
    "read_artifact_record",
    "record_closure_report",
    "load_qa_stage_results",
    "load_qa_stage_results_for_scope",
    "load_qa_findings",
    "load_qa_findings_for_scope",
]
