"""Roundtrip-Test: ProjectionAccessor write -> read via echtem SQLite.

Nutzt SQLite-Backend (AGENTKIT_ALLOW_SQLITE=1) fuer echte Persistenz.
Verifiziert, dass write_projection und read_projection tatsaechlich
persistieren und zuruecklesen koennen.

Platzierung in tests/unit/ (statt tests/integration/) weil:
- der echte SQLite-Read-Roundtrip eine reine Logik-/Persistenz-Pruefung ist und
  in tests/unit/ (sqlite-autouse) ohne Docker laeuft
- Dieser Test braucht explizit SQLite fuer den FK-69-Read-Roundtrip-Pfad
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.backend.state_backend.store.telemetry_projection_repository_misc import (
    build_projection_repositories,
)
from agentkit.backend.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)
from agentkit.backend.verify_system.stage_registry.records import (
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
    from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests

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
        detail="src/agentkit/backend/x.py:42",
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
        mode="standard",
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
        mode="standard",
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
            mode="standard",
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
# AG3-035 #5: record_qa_layer_artifacts -- fachliche QA-Schreibgrenze
# ---------------------------------------------------------------------------


class _SpyBatchWriter:
    """Spy-Implementierung des QALayerBatchWriter-Ports (AG3-035 #5)."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, object, int, str, int, object]] = []

    def persist_layer_artifacts(
        self,
        story_dir: object,
        *,
        layer_results: object,
        attempt_nr: int,
        owner_session_id: str,
        expected_ownership_epoch: int,
        projection_dir: object = None,
    ) -> tuple[str, ...]:
        self.calls.append(
            (
                story_dir,
                layer_results,
                attempt_nr,
                owner_session_id,
                expected_ownership_epoch,
                projection_dir,
            )
        )
        return ("art-spy-001",)


def test_record_qa_layer_artifacts_delegates_to_batch_port(tmp_path: Path) -> None:
    """record_qa_layer_artifacts delegiert unveraendert an den injizierten Port.

    Verifiziert: der ProjectionAccessor ist der fachliche Eintrittspunkt fuer
    den QA-Layer-Batch (FK-69 §69.4, AG3-035 #5), und die atomare Transaktion
    bleibt im Port/Driver gekapselt (kein facade-Aufruf im Accessor, AC#7).
    Der produktive End-to-End-Pfad (implementation/verify -> Accessor -> Driver)
    ist zusaetzlich in tests/unit/implementation/test_implementation_phase.py
    abgedeckt.
    """
    repos = build_projection_repositories(tmp_path)
    spy = _SpyBatchWriter()
    repos = dataclasses.replace(repos, qa_layer_batch=spy)
    accessor = ProjectionAccessor(repos)

    proj_dir = tmp_path / "proj"
    result = accessor.record_qa_layer_artifacts(
        tmp_path,
        layer_results=(),
        attempt_nr=2,
        owner_session_id="sess-spy",
        expected_ownership_epoch=1,
        projection_dir=proj_dir,
    )

    assert result == ("art-spy-001",)
    assert len(spy.calls) == 1
    (
        story_dir,
        layer_results,
        attempt_nr,
        owner_session_id,
        expected_ownership_epoch,
        projection_dir,
    ) = spy.calls[0]
    assert story_dir == tmp_path
    assert layer_results == ()
    assert attempt_nr == 2
    assert owner_session_id == "sess-spy"
    assert expected_ownership_epoch == 1
    assert projection_dir == proj_dir


def test_record_qa_layer_artifacts_runs_real_batch_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Echter Pfad-Beweis (#5/#7): produktiver Accessor-Schreibpfad ohne Spy.

    Die echte ``FacadeQALayerBatchWriter`` -> ``facade.record_layer_artifacts``
    -> Driver-Batch wird durchlaufen (kein Mock) und gibt das Driver-Ergebnis
    zurueck (FK-69 §69.4, AG3-035 #5). Die qa_stage_results-Materialisierung an
    der Persistenzgrenze ist zusaetzlich im Postgres-Contract-Test
    (tests/contract/state_backend/test_postgres_backend.py) abgedeckt.
    """
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")

    from agentkit.backend.bootstrap.composition_root import build_artifact_manager
    from agentkit.backend.phase_state_store.models import FlowExecution
    from agentkit.backend.state_backend.persistence_test_support import (
        reset_backend_cache_for_tests,
    )
    from agentkit.backend.state_backend.pipeline_runtime_store import save_flow_execution
    from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.types import StoryMode, StoryType
    from agentkit.backend.verify_system.artifacts import write_layer_artifacts
    from agentkit.backend.verify_system.protocols import (
        Finding,
        LayerResult,
        Severity,
        TrustClass,
    )

    reset_backend_cache_for_tests()
    try:
        story_dir = tmp_path / "stories" / "QA-700"
        story_dir.mkdir(parents=True, exist_ok=True)
        save_story_context(
            story_dir,
            StoryContext(
                project_key="qa-proj",
                story_id="QA-700",
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
                project_root=tmp_path / "qa-proj",
            ),
        )
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="qa-proj",
                story_id="QA-700",
                run_id="run-qa-700",
                flow_id="implementation",
                level="story",
                owner="pipeline_engine",
                status="IN_PROGRESS",
            ),
        )
        layers = (
            LayerResult(
                layer="structural",
                passed=False,
                findings=(
                    Finding(
                        layer="structural",
                        check="context_exists",
                        severity=Severity.BLOCKING,
                        message="context.json missing",
                        trust_class=TrustClass.SYSTEM,
                    ),
                ),
                metadata={"total_checks": 4},
            ),
        )
        # Quell-Artefakte (artifact_records) muessen vor der FK-69-Materialisierung
        # existieren, damit der Driver-Batch die artifact_id aufloesen kann.
        write_layer_artifacts(
            manager=build_artifact_manager(story_dir),
            story_id="QA-700",
            run_id="run-qa-700",
            layer_results=layers,
            attempt_nr=1,
        )

        accessor = ProjectionAccessor(build_projection_repositories(story_dir))
        produced = accessor.record_qa_layer_artifacts(
            story_dir,
            layer_results=layers,
            attempt_nr=1,
            # AG3-144: sqlite backend (forced above) -- no fence mirroring
            # there, so these values are accepted but ignored by the driver.
            owner_session_id="sqlite-unfenced",
            expected_ownership_epoch=0,
            projection_dir=None,
        )

        # Die echte Kette lief durch (kein Spy) und gibt das Driver-Ergebnis
        # (Tuple der Artefakt-Namen) zurueck -- die Pass-Through-Schreibgrenze
        # ist damit real ausgefuehrt, nicht nur delegiert.
        assert isinstance(produced, tuple)
        assert "structural.json" in produced
    finally:
        reset_backend_cache_for_tests()
