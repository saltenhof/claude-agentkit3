from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.verify_system.protocols import Finding, LayerResult, Severity, TrustClass
from agentkit.backend.verify_system.qa_read_models import (
    build_qa_findings,
    build_qa_stage_result,
)
from agentkit.backend.verify_system.stage_registry import StageRegistry

_REGISTRY = StageRegistry()


def _flow() -> FlowExecution:
    return FlowExecution(
        project_key="demo-project",
        story_id="AG3-777",
        run_id="run-qa-001",
        flow_id="implementation",
        level="story",
        owner="pipeline-engine",
        started_at=datetime(2026, 4, 20, 10, 0, 0, tzinfo=UTC),
    )


def _finding(
    *,
    check: str,
    severity: Severity,
    file_path: str | None = None,
    line_number: int | None = None,
    message: str | None = None,
) -> Finding:
    return Finding(
        layer="structural",
        check=check,
        severity=severity,
        message=message or f"{check} failed",
        trust_class=TrustClass.SYSTEM,
        file_path=file_path,
        line_number=line_number,
    )


def test_build_qa_stage_result_derives_counts_from_execution_protocol() -> None:
    recorded_at = datetime(2026, 4, 20, 10, 15, 0, tzinfo=UTC)
    layer_result = LayerResult(
        layer="structural",
        passed=False,
        findings=(
            _finding(
                check="context_exists",
                severity=Severity.BLOCKING,
                file_path="context.json",
                line_number=1,
            ),
            _finding(check="warning_one", severity=Severity.MINOR),
            _finding(check="warning_two", severity=Severity.MINOR),
        ),
        metadata={
            "executed_check_ids": (
                "context_exists",
                "warning_one",
                "warning_two",
                "clean_one",
                "clean_two",
                "clean_three",
                "clean_four",
                "clean_five",
            ),
            "total_checks": 8,
            "failed_checks": 1,
            "warning_checks": 2,
        },
    )

    record = build_qa_stage_result(
        _flow(),
        layer_result,
        attempt_no=2,
        artifact_id="structural.json",
        recorded_at=recorded_at,
        stage_registry=_REGISTRY,
    )

    assert record.status == "FAIL"
    assert record.blocking is True
    assert record.total_checks == 8
    assert record.failed_checks == 1
    assert record.warning_checks == 2
    assert record.artifact_id == "structural.json"


def test_build_qa_stage_result_rejects_disagreeing_explicit_count() -> None:
    result = LayerResult(
        layer="structural",
        passed=True,
        metadata={"executed_check_ids": ("artifact.protocol",), "total_checks": 2},
    )

    with pytest.raises(ValueError, match="total_checks.*disagrees"):
        build_qa_stage_result(
            _flow(),
            result,
            attempt_no=1,
            artifact_id="structural.json",
            recorded_at=datetime(2026, 8, 4, tzinfo=UTC),
            stage_registry=_REGISTRY,
        )


def test_build_qa_findings_uses_deterministic_non_text_identity() -> None:
    recorded_at = datetime(2026, 4, 20, 10, 15, 0, tzinfo=UTC)
    layer_result = LayerResult(
        layer="structural",
        passed=False,
        findings=(
            _finding(
                check="lint",
                severity=Severity.BLOCKING,
                file_path="src/app.py",
                line_number=10,
                message="first wording",
            ),
            _finding(
                check="lint",
                severity=Severity.BLOCKING,
                file_path="src/app.py",
                line_number=10,
                message="second wording",
            ),
        ),
        metadata={"executed_check_ids": ("lint",)},
    )

    records = build_qa_findings(
        _flow(),
        layer_result,
        attempt_no=2,
        artifact_id="structural.json",
        recorded_at=recorded_at,
        stage_registry=_REGISTRY,
    )

    assert len(records) == 2
    assert records[0].status == "REPORTED"
    assert records[0].blocking is True
    assert records[0].description == "first wording"
    assert records[0].finding_id != records[1].finding_id
    assert records[0].finding_id.startswith("lint-")
    assert records[1].finding_id.startswith("lint-")


def test_doc_fidelity_projections_use_canonical_stage_id() -> None:
    """Stage-result and finding rows persist the registry-owned stage ID."""
    recorded_at = datetime(2026, 4, 20, 10, 15, 0, tzinfo=UTC)
    finding = Finding(
        layer="doc_fidelity",
        check="impl_fidelity",
        severity=Severity.BLOCKING,
        message="implementation diverges from the design",
        trust_class=TrustClass.VERIFIED_LLM,
    )
    layer_result = LayerResult(
        layer="doc_fidelity",
        passed=False,
        findings=(finding,),
        metadata={"executed_check_ids": ("impl_fidelity",)},
    )

    stage_record = build_qa_stage_result(
        _flow(),
        layer_result,
        attempt_no=2,
        artifact_id="doc_fidelity.json",
        recorded_at=recorded_at,
        stage_registry=_REGISTRY,
    )
    finding_records = build_qa_findings(
        _flow(),
        layer_result,
        attempt_no=2,
        artifact_id="doc_fidelity.json",
        recorded_at=recorded_at,
        stage_registry=_REGISTRY,
    )

    assert stage_record.stage_id == "doc_fidelity_impl"
    assert stage_record.layer == "doc_fidelity"
    assert finding_records[0].stage_id == "doc_fidelity_impl"


def test_unknown_result_name_is_rejected_by_stage_projection() -> None:
    result = LayerResult(
        layer="unregistered_result",
        passed=True,
        metadata={"executed_check_ids": ("artifact.protocol",)},
    )

    with pytest.raises(ValueError, match="unknown LayerResult name"):
        build_qa_stage_result(
            _flow(),
            result,
            attempt_no=1,
            artifact_id="unknown.json",
            recorded_at=datetime(2026, 8, 4, tzinfo=UTC),
            stage_registry=_REGISTRY,
        )
