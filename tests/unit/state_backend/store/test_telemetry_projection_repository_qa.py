"""Tests for the canonical telemetry QA projection repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.qa_artifact_support import seed_qa_stage_result

from agentkit.backend.bootstrap.composition_state import build_projection_accessor
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.state_backend.persistence_test_support import (
    reset_backend_cache_for_tests,
)
from agentkit.backend.state_backend.pipeline_runtime_store import save_flow_execution
from agentkit.backend.state_backend.store.telemetry_projection_repository_qa import (
    FacadeQACheckOutcomesRepository,
    FacadeQAFindingsRepository,
    FacadeQAStageResultsRepository,
)
from agentkit.backend.verify_system.check_outcome_emitter import (
    CheckOutcomeEmitter,
    build_check_outcomes,
)
from agentkit.backend.verify_system.protocols import Finding, LayerResult, Severity, TrustClass
from agentkit.backend.verify_system.stage_registry.records import (
    CheckOutcome,
    QAStageResultRecord,
)
from agentkit.backend.verify_system.stage_registry.registry import StageRegistry

if TYPE_CHECKING:
    from pathlib import Path


def test_qa_projection_repositories_expose_no_split_writers(tmp_path: Path) -> None:
    """G2: every QA repository is read/purge-only outside the atomic batch."""
    assert not hasattr(FacadeQAStageResultsRepository(tmp_path), "write")
    assert not hasattr(FacadeQAFindingsRepository(tmp_path), "write")
    assert not hasattr(FacadeQACheckOutcomesRepository(tmp_path), "write")


def test_qa_stage_results_repository_reads_its_canonical_sqlite_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC1: stage-result reads use the repository-owned backend path."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    repository = FacadeQAStageResultsRepository(tmp_path)
    record = QAStageResultRecord(
        project_key="project",
        story_id="AG3-191",
        run_id="run-1",
        attempt_no=1,
        stage_id="structural",
        layer="structural",
        producer_component="verify-system.layer-1-structural",
        status="PASS",
        blocking=False,
        total_checks=1,
        failed_checks=0,
        warning_checks=0,
        artifact_id="artifact-1",
        recorded_at=datetime(2026, 8, 4, tzinfo=UTC),
    )

    seed_qa_stage_result(tmp_path, record)
    rows = repository.read(
        project_key="project",
        story_id="AG3-191",
        run_id="run-1",
    )

    assert rows == [record]
    reset_backend_cache_for_tests()


def test_productive_batch_projects_registered_result_without_artifact_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The productive batch projects every registry result into all QA rows."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    recorded_at = datetime(2026, 8, 4, tzinfo=UTC)
    registry = StageRegistry()
    story_dir = tmp_path / "AG3-191"
    story_dir.mkdir()
    flow = FlowExecution(
        project_key="project",
        story_id="AG3-191",
        run_id="run-sonarqube",
        flow_id="implementation",
        level="story",
        owner="pipeline-engine",
        started_at=recorded_at,
    )
    save_flow_execution(story_dir, flow)
    finding = Finding(
        layer="sonarqube_gate",
        check="sonarqube_gate",
        severity=Severity.BLOCKING,
        message="SonarQube quality gate failed",
        trust_class=TrustClass.SYSTEM,
    )
    layer_result = LayerResult(
        layer="sonarqube_gate",
        passed=False,
        findings=(finding,),
        metadata={
            "executed_check_ids": ("sonarqube_gate",),
            "total_checks": 1,
            "failed_checks": 1,
            "warning_checks": 0,
        },
    )
    outcome_records = build_check_outcomes(
        flow,
        layer_result,
        attempt_no=1,
        occurred_at=recorded_at,
        check_origin_refs=registry.resolve_check_origin_refs(["sonarqube_gate"]),
        stage_registry=registry,
    )

    produced = build_projection_accessor(story_dir).record_qa_layer_artifacts(
        story_dir,
        layer_results=(layer_result,),
        check_outcomes=tuple(outcome_records),
        stage_registry=registry,
        attempt_nr=1,
        owner_session_id="sqlite-test-owner",
        expected_ownership_epoch=1,
    )

    stage_rows = FacadeQAStageResultsRepository(story_dir).read(stage_id="sonarqube_gate")
    finding_rows = FacadeQAFindingsRepository(story_dir).read(stage_id="sonarqube_gate")
    outcome_rows = FacadeQACheckOutcomesRepository(story_dir).read(
        project_key="project",
        stage_id="sonarqube_gate",
    )
    assert produced == ()
    assert not (story_dir / "sonarqube_gate.json").exists()
    assert len(stage_rows) == 1
    assert stage_rows[0].total_checks == 1
    assert len(finding_rows) == 1
    assert finding_rows[0].check_id == "sonarqube_gate"
    assert outcome_rows == outcome_records
    reset_backend_cache_for_tests()


def test_productive_batch_validates_counts_without_artifact_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registered result cannot bypass count validation by lacking a file."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    story_dir = tmp_path / "AG3-191"
    story_dir.mkdir()
    flow = FlowExecution(
        project_key="project",
        story_id="AG3-191",
        run_id="run-invalid-count",
        flow_id="implementation",
        level="story",
        owner="pipeline-engine",
    )
    save_flow_execution(story_dir, flow)
    layer_result = LayerResult(
        layer="sonarqube_gate",
        passed=True,
        metadata={"executed_check_ids": ("sonarqube_gate",), "total_checks": 2},
    )
    check_outcomes = CheckOutcomeEmitter().build_batch(
        flow,
        (layer_result,),
        attempt_no=1,
        stage_registry=StageRegistry(),
    )

    with pytest.raises(ValueError, match="total_checks"):
        build_projection_accessor(story_dir).record_qa_layer_artifacts(
            story_dir,
            layer_results=(layer_result,),
            check_outcomes=check_outcomes,
            stage_registry=StageRegistry(),
            attempt_nr=1,
            owner_session_id="sqlite-test-owner",
            expected_ownership_epoch=1,
        )


def test_productive_batch_rejects_finding_with_clean_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The productive accessor rejects a cross-projection contradiction."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    story_dir = tmp_path / "AG3-191"
    story_dir.mkdir()
    flow = FlowExecution(
        project_key="project",
        story_id="AG3-191",
        run_id="run-contradiction",
        flow_id="implementation",
        level="story",
        owner="pipeline-engine",
    )
    save_flow_execution(story_dir, flow)
    layer_result = LayerResult(
        layer="sonarqube_gate",
        passed=False,
        findings=(
            Finding(
                layer="sonarqube_gate",
                check="sonarqube_gate",
                severity=Severity.BLOCKING,
                message="quality gate failed",
                trust_class=TrustClass.SYSTEM,
            ),
        ),
        metadata={"executed_check_ids": ("sonarqube_gate",)},
    )
    registry = StageRegistry()
    outcomes = CheckOutcomeEmitter().build_batch(
        flow,
        (layer_result,),
        attempt_no=1,
        stage_registry=registry,
    )
    contradictory = (replace(outcomes[0], outcome=CheckOutcome.CLEAN),)

    with pytest.raises(ValueError, match="findings require"):
        build_projection_accessor(story_dir).record_qa_layer_artifacts(
            story_dir,
            layer_results=(layer_result,),
            check_outcomes=contradictory,
            stage_registry=registry,
            attempt_nr=1,
            owner_session_id="sqlite-test-owner",
            expected_ownership_epoch=1,
        )

    assert FacadeQAStageResultsRepository(story_dir).read(run_id="run-invalid-count") == []
    reset_backend_cache_for_tests()
