"""Unit-Tests fuer ProjectionAccessor.

Testet:
- write_projection: jedes ProjectionKind leitet in das richtige Repository
- read_projection: Filter werden korrekt durchgereicht
- Discriminated-Union-Validierung: falscher Record-Typ -> ProjectionRecordTypeMismatchError
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.telemetry.errors import ProjectionRecordTypeMismatchError
from agentkit.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)
from agentkit.verify_system.stage_registry.records import (
    QAFindingRecord,
    QAStageResultRecord,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_qa_stage_result() -> QAStageResultRecord:
    return QAStageResultRecord(
        project_key="test-proj",
        story_id="TEST-001",
        run_id="run-abc",
        attempt_no=1,
        stage_id="structural",
        layer="structural",
        producer_component="qa-structural-check",
        status="PASS",
        blocking=False,
        total_checks=5,
        failed_checks=0,
        warning_checks=0,
        artifact_id="art-123",
        recorded_at=datetime.now(UTC),
    )


def _make_qa_finding() -> QAFindingRecord:
    return QAFindingRecord(
        project_key="test-proj",
        story_id="TEST-001",
        run_id="run-abc",
        attempt_no=1,
        stage_id="structural",
        finding_id="structural-abc123",
        check_id="mypy_error",
        status="REPORTED",
        severity="BLOCKING",
        blocking=True,
        source_component="qa-structural-check",
        artifact_id="art-123",
        occurred_at=datetime.now(UTC),
    )


def _make_story_metrics() -> StoryMetricsRecord:
    return StoryMetricsRecord(
        project_key="test-proj",
        story_id="TEST-001",
        run_id="run-abc",
        story_type="IMPLEMENTATION",
        story_size="M",
        mode="EXECUTION",
        processing_time_min=12.5,
        qa_rounds=2,
        increments=3,
        final_status="COMPLETED",
        completed_at="2026-05-25T10:00:00+00:00",
    )


def _make_repos() -> MagicMock:
    """Erzeugt einen Mock-ProjectionRepositories-Container."""
    repos = MagicMock()
    repos.qa_stage_results = MagicMock()
    repos.qa_findings = MagicMock()
    repos.story_metrics = MagicMock()
    repos.phase_state_projection = MagicMock()
    return repos


# ---------------------------------------------------------------------------
# write_projection: korrekter Record-Typ -> richtiges Repository
# ---------------------------------------------------------------------------


def test_write_qa_stage_results_calls_repo() -> None:
    """write_projection(QA_STAGE_RESULTS, QAStageResultRecord) -> qa_stage_results.write."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    record = _make_qa_stage_result()

    accessor.write_projection(ProjectionKind.QA_STAGE_RESULTS, record)

    repos.qa_stage_results.write.assert_called_once_with(record)
    repos.qa_findings.write.assert_not_called()
    repos.story_metrics.write.assert_not_called()


def test_write_qa_findings_calls_repo() -> None:
    """write_projection(QA_FINDINGS, QAFindingRecord) -> qa_findings.write."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    record = _make_qa_finding()

    accessor.write_projection(ProjectionKind.QA_FINDINGS, record)

    repos.qa_findings.write.assert_called_once_with(record)
    repos.qa_stage_results.write.assert_not_called()
    repos.story_metrics.write.assert_not_called()


def test_write_story_metrics_calls_repo() -> None:
    """write_projection(STORY_METRICS, StoryMetricsRecord) -> story_metrics.write."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    record = _make_story_metrics()

    accessor.write_projection(ProjectionKind.STORY_METRICS, record)

    repos.story_metrics.write.assert_called_once_with(record)
    repos.qa_stage_results.write.assert_not_called()
    repos.qa_findings.write.assert_not_called()


# ---------------------------------------------------------------------------
# write_projection: falscher Record-Typ -> ProjectionRecordTypeMismatchError
# ---------------------------------------------------------------------------


def test_wrong_record_type_for_qa_stage_results_raises() -> None:
    """QA_STAGE_RESULTS mit QAFindingRecord -> ProjectionRecordTypeMismatchError."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    wrong_record = _make_qa_finding()  # falscher Typ

    with pytest.raises(ProjectionRecordTypeMismatchError) as exc_info:
        accessor.write_projection(ProjectionKind.QA_STAGE_RESULTS, wrong_record)

    err = exc_info.value
    assert err.kind == ProjectionKind.QA_STAGE_RESULTS
    assert err.expected == QAStageResultRecord
    assert err.received == QAFindingRecord
    repos.qa_stage_results.write.assert_not_called()


def test_wrong_record_type_for_qa_findings_raises() -> None:
    """QA_FINDINGS mit StoryMetricsRecord -> ProjectionRecordTypeMismatchError."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    wrong_record = _make_story_metrics()

    with pytest.raises(ProjectionRecordTypeMismatchError):
        accessor.write_projection(ProjectionKind.QA_FINDINGS, wrong_record)

    repos.qa_findings.write.assert_not_called()


def test_wrong_record_type_for_story_metrics_raises() -> None:
    """STORY_METRICS mit QAStageResultRecord -> ProjectionRecordTypeMismatchError."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    wrong_record = _make_qa_stage_result()

    with pytest.raises(ProjectionRecordTypeMismatchError):
        accessor.write_projection(ProjectionKind.STORY_METRICS, wrong_record)

    repos.story_metrics.write.assert_not_called()


# ---------------------------------------------------------------------------
# write_projection: nicht-implementierte Kinds -> NotImplementedError
# ---------------------------------------------------------------------------


def test_phase_state_projection_write_raises_not_implemented() -> None:
    """PHASE_STATE_PROJECTION hat keinen Schreibpfad im Accessor (PhaseExecutor schreibt)."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    record = _make_story_metrics()  # Typ spielt keine Rolle; Kind fehlt

    with pytest.raises(NotImplementedError):
        accessor.write_projection(ProjectionKind.PHASE_STATE_PROJECTION, record)


def test_fc_incidents_write_raises_not_implemented() -> None:
    """FC_INCIDENTS Schreibpfad ist nach AG3-028 vertagt."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    record = _make_story_metrics()

    with pytest.raises(NotImplementedError):
        accessor.write_projection(ProjectionKind.FC_INCIDENTS, record)


# ---------------------------------------------------------------------------
# read_projection: Filter werden korrekt durchgereicht
# ---------------------------------------------------------------------------


def test_read_qa_stage_results_passes_filter() -> None:
    """read_projection(QA_STAGE_RESULTS, filter) leitet Filter an Repository."""
    repos = _make_repos()
    repos.qa_stage_results.read.return_value = []
    accessor = ProjectionAccessor(repos)
    f = ProjectionFilter(
        project_key="pk",
        story_id="S-001",
        run_id="run-xyz",
        attempt_no=2,
        stage_id="structural",
    )

    result = accessor.read_projection(ProjectionKind.QA_STAGE_RESULTS, f)

    repos.qa_stage_results.read.assert_called_once_with(
        project_key="pk",
        story_id="S-001",
        run_id="run-xyz",
        attempt_no=2,
        stage_id="structural",
    )
    assert result == []


def test_read_qa_findings_passes_filter() -> None:
    """read_projection(QA_FINDINGS, filter) leitet Filter an Repository."""
    repos = _make_repos()
    expected = [_make_qa_finding()]
    repos.qa_findings.read.return_value = expected
    accessor = ProjectionAccessor(repos)
    f = ProjectionFilter(story_id="S-001", run_id="run-xyz")

    result = accessor.read_projection(ProjectionKind.QA_FINDINGS, f)

    repos.qa_findings.read.assert_called_once_with(
        project_key=None,
        story_id="S-001",
        run_id="run-xyz",
        attempt_no=None,
        stage_id=None,
    )
    assert result == expected


def test_read_story_metrics_passes_filter() -> None:
    """read_projection(STORY_METRICS, filter) leitet Filter an Repository."""
    repos = _make_repos()
    expected = [_make_story_metrics()]
    repos.story_metrics.read.return_value = expected
    accessor = ProjectionAccessor(repos)
    f = ProjectionFilter(project_key="pk", story_id="S-001")

    result = accessor.read_projection(ProjectionKind.STORY_METRICS, f)

    repos.story_metrics.read.assert_called_once_with(
        project_key="pk",
        story_id="S-001",
        run_id=None,
    )
    assert result == expected


def test_read_fc_incidents_raises_not_implemented() -> None:
    """FC_*-Read-Pfade sind nach AG3-028 vertagt."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    f = ProjectionFilter()

    with pytest.raises(NotImplementedError):
        accessor.read_projection(ProjectionKind.FC_INCIDENTS, f)


def test_read_phase_state_projection_raises_not_implemented() -> None:
    """PHASE_STATE_PROJECTION-Read via Accessor ist in AG3-035 nicht implementiert."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    f = ProjectionFilter()

    with pytest.raises(NotImplementedError):
        accessor.read_projection(ProjectionKind.PHASE_STATE_PROJECTION, f)


# ---------------------------------------------------------------------------
# ProjectionRecordTypeMismatchError -- Fehlerattribute pruefen
# ---------------------------------------------------------------------------


def test_mismatch_error_attributes() -> None:
    """ProjectionRecordTypeMismatchError hat kind/expected/received."""
    err = ProjectionRecordTypeMismatchError(
        kind=ProjectionKind.QA_STAGE_RESULTS,
        expected=QAStageResultRecord,
        received=StoryMetricsRecord,
    )
    assert err.kind == ProjectionKind.QA_STAGE_RESULTS
    assert err.expected == QAStageResultRecord
    assert err.received == StoryMetricsRecord
    assert "QAStageResultRecord" in str(err)
    assert "StoryMetricsRecord" in str(err)
