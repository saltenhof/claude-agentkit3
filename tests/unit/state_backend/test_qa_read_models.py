from __future__ import annotations

from datetime import UTC, datetime

from agentkit.phase_state_store.models import FlowExecution
from agentkit.qa.protocols import Finding, LayerResult, Severity, TrustClass
from agentkit.state_backend.qa_read_models import (
    build_qa_findings,
    build_qa_stage_result,
)


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


def test_build_qa_stage_result_prefers_explicit_count_metadata() -> None:
    recorded_at = datetime(2026, 4, 20, 10, 15, 0, tzinfo=UTC)
    layer_result = LayerResult(
        layer="structural",
        passed=False,
        findings=(
            _finding(
                check="context_exists",
                severity=Severity.CRITICAL,
                file_path="context.json",
                line_number=1,
            ),
        ),
        metadata={
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
    )

    assert record.status == "FAIL"
    assert record.blocking is True
    assert record.total_checks == 8
    assert record.failed_checks == 1
    assert record.warning_checks == 2
    assert record.artifact_id == "structural.json"


def test_build_qa_findings_uses_deterministic_non_text_identity() -> None:
    recorded_at = datetime(2026, 4, 20, 10, 15, 0, tzinfo=UTC)
    layer_result = LayerResult(
        layer="structural",
        passed=False,
        findings=(
            _finding(
                check="lint",
                severity=Severity.HIGH,
                file_path="src/app.py",
                line_number=10,
                message="first wording",
            ),
            _finding(
                check="lint",
                severity=Severity.HIGH,
                file_path="src/app.py",
                line_number=10,
                message="second wording",
            ),
        ),
    )

    records = build_qa_findings(
        _flow(),
        layer_result,
        attempt_no=2,
        artifact_id="structural.json",
        recorded_at=recorded_at,
    )

    assert len(records) == 2
    assert records[0].status == "REPORTED"
    assert records[0].blocking is True
    assert records[0].description == "first wording"
    assert records[0].finding_id != records[1].finding_id
    assert records[0].finding_id.startswith("lint-")
    assert records[1].finding_id.startswith("lint-")
