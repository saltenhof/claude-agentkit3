"""FK-69 QA read-model materialization helpers for the canonical backend."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha1
from typing import TYPE_CHECKING

from agentkit.qa.protocols import Severity
from agentkit.state_backend.records import QAFindingRecord, QAStageResultRecord

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.phase_state_store.models import FlowExecution
    from agentkit.qa.protocols import Finding, LayerResult


def producer_component_for_layer(layer: str) -> str:
    """Return the canonical producer component for a QA layer."""

    producers = {
        "structural": "qa-structural-check",
        "semantic": "qa-semantic-review",
        "adversarial": "qa-adversarial",
    }
    return producers.get(layer, "qa-layer")


def build_qa_stage_result(
    flow: FlowExecution,
    layer_result: LayerResult,
    *,
    attempt_no: int,
    artifact_id: str,
    recorded_at: datetime,
) -> QAStageResultRecord:
    """Project one layer result into the FK-69 stage-result read model."""

    total_checks = _count_from_metadata(
        layer_result.metadata,
        "total_checks",
        fallback=len(layer_result.findings),
    )
    failed_checks = _count_from_metadata(
        layer_result.metadata,
        "failed_checks",
        fallback=len(layer_result.blocking_findings),
    )
    warning_checks = _count_from_metadata(
        layer_result.metadata,
        "warning_checks",
        fallback=sum(
            1 for finding in layer_result.findings if not _finding_blocks(finding)
        ),
    )

    return QAStageResultRecord(
        project_key=flow.project_key,
        story_id=flow.story_id,
        run_id=flow.run_id,
        attempt_no=attempt_no,
        stage_id=layer_result.layer,
        layer=layer_result.layer,
        producer_component=producer_component_for_layer(layer_result.layer),
        status="PASS" if layer_result.passed else "FAIL",
        blocking=bool(layer_result.blocking_findings),
        total_checks=total_checks,
        failed_checks=failed_checks,
        warning_checks=warning_checks,
        artifact_id=artifact_id,
        recorded_at=recorded_at,
    )


def build_qa_findings(
    flow: FlowExecution,
    layer_result: LayerResult,
    *,
    attempt_no: int,
    artifact_id: str,
    recorded_at: datetime,
) -> list[QAFindingRecord]:
    """Project one layer result into FK-69 finding records."""

    producer_component = producer_component_for_layer(layer_result.layer)
    records: list[QAFindingRecord] = []
    seen_per_key: defaultdict[tuple[str, str, int | None, str, str], int]
    seen_per_key = defaultdict(int)

    for finding in sorted(layer_result.findings, key=_finding_sort_key):
        identity_key = _finding_identity_key(finding)
        seen_per_key[identity_key] += 1
        records.append(
            QAFindingRecord(
                project_key=flow.project_key,
                story_id=flow.story_id,
                run_id=flow.run_id,
                attempt_no=attempt_no,
                stage_id=layer_result.layer,
                finding_id=_finding_id(identity_key, seen_per_key[identity_key]),
                check_id=finding.check,
                status="REPORTED",
                severity=finding.severity.value,
                blocking=_finding_blocks(finding),
                source_component=producer_component,
                artifact_id=artifact_id,
                occurred_at=recorded_at,
                description=finding.message,
                detail=_finding_detail(finding),
                metadata=_finding_metadata(finding),
            ),
        )

    return records


def _count_from_metadata(
    metadata: dict[str, object],
    key: str,
    *,
    fallback: int,
) -> int:
    raw = metadata.get(key)
    if isinstance(raw, int) and raw >= 0:
        return raw
    return fallback


def _finding_blocks(finding: Finding) -> bool:
    return finding.severity in (Severity.CRITICAL, Severity.HIGH)


def _finding_identity_key(
    finding: Finding,
) -> tuple[str, str, int | None, str, str]:
    return (
        finding.check,
        finding.file_path or "",
        finding.line_number,
        finding.severity.value,
        finding.trust_class.value,
    )


def _finding_id(
    identity_key: tuple[str, str, int | None, str, str],
    occurrence: int,
) -> str:
    digest = sha1(
        "|".join(
            (
                identity_key[0],
                identity_key[1],
                "" if identity_key[2] is None else str(identity_key[2]),
                identity_key[3],
                identity_key[4],
                str(occurrence),
            ),
        ).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:12]
    return f"{identity_key[0]}-{digest}"


def _finding_sort_key(finding: Finding) -> tuple[str, str, int, str, str]:
    return (
        finding.check,
        finding.file_path or "",
        finding.line_number if finding.line_number is not None else -1,
        finding.severity.value,
        finding.trust_class.value,
    )


def _finding_detail(finding: Finding) -> str | None:
    if finding.file_path is None:
        return None
    if finding.line_number is None:
        return finding.file_path
    return f"{finding.file_path}:{finding.line_number}"


def _finding_metadata(finding: Finding) -> dict[str, object]:
    metadata: dict[str, object] = {
        "trust_class": finding.trust_class.value,
    }
    if finding.file_path is not None:
        metadata["file_path"] = finding.file_path
    if finding.line_number is not None:
        metadata["line_number"] = finding.line_number
    if finding.suggestion is not None:
        metadata["suggestion"] = finding.suggestion
    return metadata
