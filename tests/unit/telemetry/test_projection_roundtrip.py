"""Roundtrip-Test: ProjectionAccessor write -> read via echtem SQLite.

Nutzt SQLite-Backend (AGENTKIT_ALLOW_SQLITE=1) fuer echte Persistenz.
Verifiziert, dass write_projection und read_projection tatsaechlich
persistieren und zuruecklesen koennen.

Platzierung in tests/unit/ (statt tests/integration/) weil:
- tests/integration/ erzwingt via conftest postgres_runtime_env fuer alle Tests
- Dieser Test braucht explizit SQLite fuer den FK-69-Read-Roundtrip-Pfad
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
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


@pytest.fixture()
def sqlite_accessor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ProjectionAccessor:
    """Erzeugt ProjectionAccessor gegen echtes SQLite via tmp_path."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    from agentkit.state_backend.store.facade import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    repos = build_projection_repositories(tmp_path)
    yield ProjectionAccessor(repos)
    reset_backend_cache_for_tests()


# ---------------------------------------------------------------------------
# QAStageResultRecord Roundtrip
# ---------------------------------------------------------------------------


def test_qa_stage_result_write_read_roundtrip(sqlite_accessor: ProjectionAccessor) -> None:
    """write_projection(QA_STAGE_RESULTS) -> read_projection liefert denselben Record."""
    record = QAStageResultRecord(
        project_key="int-proj",
        story_id="INT-001",
        run_id="run-integration",
        attempt_no=1,
        stage_id="structural",
        layer="structural",
        producer_component="qa-structural-check",
        status="PASS",
        blocking=False,
        total_checks=10,
        failed_checks=0,
        warning_checks=1,
        artifact_id="art-int-001",
        recorded_at=datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC),
    )

    sqlite_accessor.write_projection(ProjectionKind.QA_STAGE_RESULTS, record)

    results = sqlite_accessor.read_projection(
        ProjectionKind.QA_STAGE_RESULTS,
        ProjectionFilter(
            project_key="int-proj",
            story_id="INT-001",
            run_id="run-integration",
        ),
    )

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, QAStageResultRecord)
    assert r.project_key == "int-proj"
    assert r.story_id == "INT-001"
    assert r.run_id == "run-integration"
    assert r.attempt_no == 1
    assert r.stage_id == "structural"
    assert r.status == "PASS"
    assert r.total_checks == 10
    assert r.blocking is False


# ---------------------------------------------------------------------------
# QAFindingRecord Roundtrip
# ---------------------------------------------------------------------------


def test_qa_finding_write_read_roundtrip(sqlite_accessor: ProjectionAccessor) -> None:
    """write_projection(QA_FINDINGS) -> read_projection liefert denselben Record."""
    record = QAFindingRecord(
        project_key="int-proj",
        story_id="INT-002",
        run_id="run-integration",
        attempt_no=1,
        stage_id="structural",
        finding_id="structural-abc001",
        check_id="mypy_error",
        status="REPORTED",
        severity="BLOCKING",
        blocking=True,
        source_component="qa-structural-check",
        artifact_id="art-int-002",
        occurred_at=datetime(2026, 5, 25, 10, 1, 0, tzinfo=UTC),
        description="Type error in module X",
        detail="src/agentkit/x.py:42",
        metadata={"trust_class": "SYSTEM"},
    )

    sqlite_accessor.write_projection(ProjectionKind.QA_FINDINGS, record)

    results = sqlite_accessor.read_projection(
        ProjectionKind.QA_FINDINGS,
        ProjectionFilter(story_id="INT-002", run_id="run-integration"),
    )

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, QAFindingRecord)
    assert r.finding_id == "structural-abc001"
    assert r.check_id == "mypy_error"
    assert r.blocking is True
    assert r.description == "Type error in module X"


# ---------------------------------------------------------------------------
# StoryMetricsRecord Roundtrip
# ---------------------------------------------------------------------------


def test_story_metrics_write_read_roundtrip(sqlite_accessor: ProjectionAccessor) -> None:
    """write_projection(STORY_METRICS) -> read_projection liefert denselben Record."""
    record = StoryMetricsRecord(
        project_key="int-proj",
        story_id="INT-003",
        run_id="run-integration",
        story_type="IMPLEMENTATION",
        story_size="M",
        mode="EXECUTION",
        processing_time_min=15.5,
        qa_rounds=2,
        increments=4,
        final_status="COMPLETED",
        completed_at="2026-05-25T10:00:00+00:00",
    )

    sqlite_accessor.write_projection(ProjectionKind.STORY_METRICS, record)

    results = sqlite_accessor.read_projection(
        ProjectionKind.STORY_METRICS,
        ProjectionFilter(
            project_key="int-proj",
            story_id="INT-003",
            run_id="run-integration",
        ),
    )

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, StoryMetricsRecord)
    assert r.story_id == "INT-003"
    assert r.qa_rounds == 2
    assert r.processing_time_min == pytest.approx(15.5)
    assert r.final_status == "COMPLETED"


# ---------------------------------------------------------------------------
# purge_run loescht echte Zeilen
# ---------------------------------------------------------------------------


def test_purge_run_removes_story_metrics(sqlite_accessor: ProjectionAccessor) -> None:
    """purge_run(project_key, story_id, run_id) entfernt story_metrics aus SQLite."""
    record = StoryMetricsRecord(
        project_key="int-proj",
        story_id="INT-004",
        run_id="run-to-purge",
        story_type="IMPLEMENTATION",
        story_size="S",
        mode="EXECUTION",
        processing_time_min=5.0,
        qa_rounds=1,
        increments=1,
        final_status="COMPLETED",
        completed_at="2026-05-25T11:00:00+00:00",
    )
    sqlite_accessor.write_projection(ProjectionKind.STORY_METRICS, record)

    before = sqlite_accessor.read_projection(
        ProjectionKind.STORY_METRICS,
        ProjectionFilter(story_id="INT-004", run_id="run-to-purge"),
    )
    assert len(before) == 1

    result = sqlite_accessor.purge_run("int-proj", "INT-004", "run-to-purge")

    assert result.purged_rows.get(ProjectionKind.STORY_METRICS, 0) >= 1
    assert result.errors == []

    after = sqlite_accessor.read_projection(
        ProjectionKind.STORY_METRICS,
        ProjectionFilter(story_id="INT-004", run_id="run-to-purge"),
    )
    assert len(after) == 0


def test_purge_run_does_not_affect_other_runs(sqlite_accessor: ProjectionAccessor) -> None:
    """purge_run(run_id=A) loescht NICHT run_id=B der gleichen Story."""

    def _make_rec(run_id: str) -> StoryMetricsRecord:
        return StoryMetricsRecord(
            project_key="int-proj",
            story_id="INT-005",
            run_id=run_id,
            story_type="IMPLEMENTATION",
            story_size="S",
            mode="EXECUTION",
            processing_time_min=1.0,
            qa_rounds=1,
            increments=1,
            final_status="COMPLETED",
            completed_at="2026-05-25T12:00:00+00:00",
        )

    sqlite_accessor.write_projection(ProjectionKind.STORY_METRICS, _make_rec("run-A"))
    sqlite_accessor.write_projection(ProjectionKind.STORY_METRICS, _make_rec("run-B"))

    sqlite_accessor.purge_run("int-proj", "INT-005", "run-A")

    after_a = sqlite_accessor.read_projection(
        ProjectionKind.STORY_METRICS,
        ProjectionFilter(story_id="INT-005", run_id="run-A"),
    )
    assert len(after_a) == 0

    after_b = sqlite_accessor.read_projection(
        ProjectionKind.STORY_METRICS,
        ProjectionFilter(story_id="INT-005", run_id="run-B"),
    )
    assert len(after_b) == 1


def test_purge_run_removes_qa_stage_results(sqlite_accessor: ProjectionAccessor) -> None:
    """purge_run entfernt qa_stage_results aus SQLite."""
    record = QAStageResultRecord(
        project_key="int-proj",
        story_id="INT-006",
        run_id="run-purge-qa",
        attempt_no=1,
        stage_id="structural",
        layer="structural",
        producer_component="qa-structural-check",
        status="FAIL",
        blocking=True,
        total_checks=5,
        failed_checks=2,
        warning_checks=0,
        artifact_id="art-006",
        recorded_at=datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC),
    )
    sqlite_accessor.write_projection(ProjectionKind.QA_STAGE_RESULTS, record)

    before = sqlite_accessor.read_projection(
        ProjectionKind.QA_STAGE_RESULTS,
        ProjectionFilter(story_id="INT-006", run_id="run-purge-qa"),
    )
    assert len(before) == 1

    result = sqlite_accessor.purge_run("int-proj", "INT-006", "run-purge-qa")

    assert result.purged_rows.get(ProjectionKind.QA_STAGE_RESULTS, 0) >= 1

    after = sqlite_accessor.read_projection(
        ProjectionKind.QA_STAGE_RESULTS,
        ProjectionFilter(story_id="INT-006", run_id="run-purge-qa"),
    )
    assert len(after) == 0


# ---------------------------------------------------------------------------
# Befund D (AG3-035 Remediation): write_qa_layer_batch -- Accessor-Schreibgrenze
# ---------------------------------------------------------------------------


def test_write_qa_layer_batch_persists_stage_and_findings(
    sqlite_accessor: ProjectionAccessor,
) -> None:
    """write_qa_layer_batch schreibt stage_result + findings via Accessor-Repos.

    Verifiziert: ProjectionAccessor ist die EINE Schreibgrenze fuer FK-69-QA-
    Read-Models (FK-69 §69.4, Befund D AG3-035 Remediation).
    """
    stage_record = QAStageResultRecord(
        project_key="int-proj",
        story_id="INT-007",
        run_id="run-batch",
        attempt_no=1,
        stage_id="structural",
        layer="structural",
        producer_component="qa-structural-check",
        status="FAIL",
        blocking=True,
        total_checks=3,
        failed_checks=1,
        warning_checks=0,
        artifact_id="art-007",
        recorded_at=datetime(2026, 5, 25, 13, 0, 0, tzinfo=UTC),
    )
    finding_record = QAFindingRecord(
        project_key="int-proj",
        story_id="INT-007",
        run_id="run-batch",
        attempt_no=1,
        stage_id="structural",
        finding_id="structural-batch001",
        check_id="mypy_error",
        status="REPORTED",
        severity="BLOCKING",
        blocking=True,
        source_component="qa-structural-check",
        artifact_id="art-007",
        occurred_at=datetime(2026, 5, 25, 13, 0, 0, tzinfo=UTC),
        description="Batch write test finding",
    )

    # write_qa_layer_batch ist der Schreibpfad des Accessors (Befund D)
    sqlite_accessor.write_qa_layer_batch(stage_record, [finding_record])

    stages = sqlite_accessor.read_projection(
        ProjectionKind.QA_STAGE_RESULTS,
        ProjectionFilter(story_id="INT-007", run_id="run-batch"),
    )
    assert len(stages) == 1
    assert isinstance(stages[0], QAStageResultRecord)
    assert stages[0].status == "FAIL"
    assert stages[0].failed_checks == 1

    findings = sqlite_accessor.read_projection(
        ProjectionKind.QA_FINDINGS,
        ProjectionFilter(story_id="INT-007", run_id="run-batch"),
    )
    assert len(findings) == 1
    assert isinstance(findings[0], QAFindingRecord)
    assert findings[0].finding_id == "structural-batch001"
    assert findings[0].description == "Batch write test finding"


def test_write_qa_layer_batch_empty_findings(sqlite_accessor: ProjectionAccessor) -> None:
    """write_qa_layer_batch mit leerer findings-Liste ist erlaubt (PASS ohne Findings)."""
    stage_record = QAStageResultRecord(
        project_key="int-proj",
        story_id="INT-008",
        run_id="run-batch-empty",
        attempt_no=1,
        stage_id="structural",
        layer="structural",
        producer_component="qa-structural-check",
        status="PASS",
        blocking=False,
        total_checks=5,
        failed_checks=0,
        warning_checks=0,
        artifact_id="art-008",
        recorded_at=datetime(2026, 5, 25, 14, 0, 0, tzinfo=UTC),
    )

    sqlite_accessor.write_qa_layer_batch(stage_record, [])

    stages = sqlite_accessor.read_projection(
        ProjectionKind.QA_STAGE_RESULTS,
        ProjectionFilter(story_id="INT-008", run_id="run-batch-empty"),
    )
    assert len(stages) == 1
    assert stages[0].status == "PASS"

    findings = sqlite_accessor.read_projection(
        ProjectionKind.QA_FINDINGS,
        ProjectionFilter(story_id="INT-008", run_id="run-batch-empty"),
    )
    assert findings == []
