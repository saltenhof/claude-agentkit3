"""Tests for the canonical telemetry QA projection repository."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest
from tests.qa_artifact_support import (
    record_qa_layer_artifacts,
    seed_qa_stage_result,
    write_qa_layer_envelopes,
)

from agentkit.backend.bootstrap.composition_state import build_projection_accessor
from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.state_backend.persistence_test_support import (
    reset_backend_cache_for_tests,
)
from agentkit.backend.state_backend.pipeline_runtime_store import save_flow_execution
from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
    _sqlite_connect_qa,
)
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
    """G2: QA repositories expose neither split writes nor split purges."""
    assert not hasattr(FacadeQAStageResultsRepository(tmp_path), "write")
    assert not hasattr(FacadeQAFindingsRepository(tmp_path), "write")
    assert not hasattr(FacadeQACheckOutcomesRepository(tmp_path), "write")
    assert not hasattr(FacadeQAStageResultsRepository(tmp_path), "purge_run")
    assert not hasattr(FacadeQAFindingsRepository(tmp_path), "purge_run")
    assert not hasattr(FacadeQACheckOutcomesRepository(tmp_path), "purge_run")


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
    artifact_references = write_qa_layer_envelopes(
        story_dir,
        layer_results=(layer_result,),
        stage_registry=registry,
        attempt_nr=1,
    )
    layer_result = replace(
        layer_result,
        artifact_reference=artifact_references[layer_result.layer],
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
    assert stage_rows[0].artifact_id == artifact_references["sonarqube_gate"].record_key
    assert stage_rows[0].total_checks == 1
    assert len(finding_rows) == 1
    assert finding_rows[0].check_id == "sonarqube_gate"
    assert finding_rows[0].artifact_id == artifact_references["sonarqube_gate"].record_key
    assert outcome_rows == outcome_records
    reset_backend_cache_for_tests()


def test_attempt_rewrite_removes_omitted_stage_snapshot_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I2: a smaller rewrite replaces the complete attempt snapshot."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    story_dir = tmp_path / "AG3-191"
    story_dir.mkdir()
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="project",
            story_id="AG3-191",
            run_id="run-smaller-rewrite",
            flow_id="implementation",
            level="story",
            owner="pipeline-engine",
        ),
    )
    structural = LayerResult(
        layer="structural",
        passed=True,
        metadata={"executed_check_ids": ()},
    )
    omitted = LayerResult(
        layer="doc_fidelity",
        passed=False,
        findings=(
            Finding(
                layer="doc_fidelity",
                check="doc_fidelity.missing_docstring",
                severity=Severity.BLOCKING,
                message="missing docstring",
                trust_class=TrustClass.VERIFIED_LLM,
            ),
        ),
        metadata={
            "executed_check_ids": ("doc_fidelity.missing_docstring",),
        },
    )
    registry = StageRegistry()
    for results in ((structural, omitted), (structural,)):
        record_qa_layer_artifacts(
            story_dir,
            layer_results=results,
            stage_registry=registry,
            attempt_nr=1,
            owner_session_id="sqlite-test-owner",
            expected_ownership_epoch=1,
        )

    stages = FacadeQAStageResultsRepository(story_dir).read(
        project_key="project",
        run_id="run-smaller-rewrite",
        attempt_no=1,
    )
    findings = FacadeQAFindingsRepository(story_dir).read(
        project_key="project",
        run_id="run-smaller-rewrite",
        attempt_no=1,
    )
    outcomes = FacadeQACheckOutcomesRepository(story_dir).read(
        project_key="project",
        run_id="run-smaller-rewrite",
        attempt_no=1,
    )
    assert [row.layer for row in stages] == ["structural"]
    assert findings == []
    assert outcomes == []
    reset_backend_cache_for_tests()


@pytest.mark.parametrize(
    ("scope_field", "foreign_value"),
    (("project_key", "foreign-project"), ("run_id", "foreign-run")),
)
def test_attempt_rewrite_rejects_foreign_outcome_scope_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope_field: str,
    foreign_value: str,
) -> None:
    """I2: a batch cannot delete one snapshot and insert another scope."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    story_dir = tmp_path / "AG3-191"
    story_dir.mkdir()
    flow = FlowExecution(
        project_key="project",
        story_id="AG3-191",
        run_id="run-scope-guard",
        flow_id="implementation",
        level="story",
        owner="pipeline-engine",
    )
    save_flow_execution(story_dir, flow)
    result = LayerResult(
        layer="structural",
        passed=True,
        metadata={"executed_check_ids": ("context_exists",)},
    )
    registry = StageRegistry()
    record_qa_layer_artifacts(
        story_dir,
        layer_results=(result,),
        stage_registry=registry,
        attempt_nr=1,
        owner_session_id="sqlite-test-owner",
        expected_ownership_epoch=1,
    )
    repositories = (
        FacadeQAStageResultsRepository(story_dir),
        FacadeQAFindingsRepository(story_dir),
        FacadeQACheckOutcomesRepository(story_dir),
    )
    before = tuple(repository.read(project_key="project", run_id=flow.run_id, attempt_no=1) for repository in repositories)
    references = write_qa_layer_envelopes(
        story_dir,
        layer_results=(result,),
        stage_registry=registry,
        attempt_nr=1,
    )
    referenced_result = replace(
        result,
        artifact_reference=references[result.layer],
    )
    outcomes = CheckOutcomeEmitter().build_batch(
        flow,
        (referenced_result,),
        attempt_no=1,
        stage_registry=registry,
    )
    foreign_outcome = replace(outcomes[0], **{scope_field: foreign_value})

    with pytest.raises(CorruptStateError, match="outcome scope"):
        build_projection_accessor(story_dir).record_qa_layer_artifacts(
            story_dir,
            layer_results=(referenced_result,),
            check_outcomes=(foreign_outcome,),
            stage_registry=registry,
            attempt_nr=1,
            owner_session_id="sqlite-test-owner",
            expected_ownership_epoch=1,
        )

    after = tuple(repository.read(project_key="project", run_id=flow.run_id, attempt_no=1) for repository in repositories)
    assert after == before
    reset_backend_cache_for_tests()


def test_attempt_rewrite_rejects_duplicate_outcome_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I2: duplicate outcome identities fail before snapshot replacement."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    story_dir = tmp_path / "AG3-191"
    story_dir.mkdir()
    flow = FlowExecution(
        project_key="project",
        story_id="AG3-191",
        run_id="run-duplicate-guard",
        flow_id="implementation",
        level="story",
        owner="pipeline-engine",
    )
    save_flow_execution(story_dir, flow)
    result = LayerResult(
        layer="structural",
        passed=True,
        metadata={"executed_check_ids": ("context_exists",)},
    )
    registry = StageRegistry()
    record_qa_layer_artifacts(
        story_dir,
        layer_results=(result,),
        stage_registry=registry,
        attempt_nr=1,
        owner_session_id="sqlite-test-owner",
        expected_ownership_epoch=1,
    )
    repositories = (
        FacadeQAStageResultsRepository(story_dir),
        FacadeQAFindingsRepository(story_dir),
        FacadeQACheckOutcomesRepository(story_dir),
    )
    before = tuple(repository.read(project_key="project", run_id=flow.run_id, attempt_no=1) for repository in repositories)
    references = write_qa_layer_envelopes(
        story_dir,
        layer_results=(result,),
        stage_registry=registry,
        attempt_nr=1,
    )
    referenced_result = replace(
        result,
        artifact_reference=references[result.layer],
    )
    outcomes = CheckOutcomeEmitter().build_batch(
        flow,
        (referenced_result,),
        attempt_no=1,
        stage_registry=registry,
    )

    with pytest.raises(ValueError, match="duplicate outcome identities"):
        build_projection_accessor(story_dir).record_qa_layer_artifacts(
            story_dir,
            layer_results=(referenced_result,),
            check_outcomes=(outcomes[0], outcomes[0]),
            stage_registry=registry,
            attempt_nr=1,
            owner_session_id="sqlite-test-owner",
            expected_ownership_epoch=1,
        )

    after = tuple(repository.read(project_key="project", run_id=flow.run_id, attempt_no=1) for repository in repositories)
    assert after == before
    reset_backend_cache_for_tests()


def test_driver_rejects_foreign_stage_scope_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I2: the exported driver boundary validates the complete row batch."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    story_dir = tmp_path / "AG3-191"
    story_dir.mkdir()
    flow = FlowExecution(
        project_key="project",
        story_id="AG3-191",
        run_id="run-driver-scope",
        flow_id="implementation",
        level="story",
        owner="pipeline-engine",
    )
    save_flow_execution(story_dir, flow)
    result = LayerResult(
        layer="structural",
        passed=True,
        metadata={"executed_check_ids": ("context_exists",)},
    )
    registry = StageRegistry()
    record_qa_layer_artifacts(
        story_dir,
        layer_results=(result,),
        stage_registry=registry,
        attempt_nr=1,
        owner_session_id="sqlite-test-owner",
        expected_ownership_epoch=1,
    )
    stage_repository = FacadeQAStageResultsRepository(story_dir)
    before = stage_repository.read(project_key="project", run_id=flow.run_id, attempt_no=1)

    from agentkit.backend.state_backend import persistence_mappers
    from agentkit.backend.state_backend.state_backend_connection_manager import (
        _backend_module,
    )

    backend = _backend_module()
    flow_row = backend.load_flow_execution_row(story_dir)
    references = write_qa_layer_envelopes(
        story_dir,
        layer_results=(result,),
        stage_registry=registry,
        attempt_nr=1,
    )
    payload_rows = persistence_mappers.build_qa_layer_payload_rows(
        flow_row,
        (result,),
        attempt_nr=1,
        stage_registry=registry,
        artifact_references=references,
    )
    stage_row = dict(cast("dict[str, object]", payload_rows[0]["stage_row"]))
    stage_row["run_id"] = "foreign-run"
    payload_rows[0]["stage_row"] = stage_row
    outcome = CheckOutcomeEmitter().build_batch(
        flow,
        (result,),
        attempt_no=1,
        stage_registry=registry,
    )[0]
    outcome_rows = [
        {
            "project_key": outcome.project_key,
            "story_id": outcome.story_id,
            "run_id": outcome.run_id,
            "stage_id": outcome.stage_id,
            "attempt_no": outcome.attempt_no,
            "check_id": outcome.check_id,
            "outcome": str(outcome.outcome),
            "occurred_at": outcome.occurred_at.isoformat(),
            "check_proposal_ref": outcome.check_proposal_ref,
            "override_id": outcome.override_id,
        }
    ]

    with pytest.raises(CorruptStateError, match="stage scope"):
        backend.persist_layer_artifact_rows(
            story_dir,
            flow_row=flow_row,
            layer_payload_rows=payload_rows,
            check_outcome_rows=outcome_rows,
            attempt_nr=1,
            owner_session_id="sqlite-test-owner",
            expected_ownership_epoch=1,
        )

    assert stage_repository.read(project_key="project", run_id=flow.run_id, attempt_no=1) == before
    reset_backend_cache_for_tests()


def test_atomic_qa_reset_rolls_back_when_second_delete_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I1: a fault in the second delete leaves all three projections intact."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    story_dir = tmp_path / "AG3-191"
    story_dir.mkdir()
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="project",
            story_id="AG3-191",
            run_id="run-reset-fault",
            flow_id="implementation",
            level="story",
            owner="pipeline-engine",
        ),
    )
    result = LayerResult(
        layer="structural",
        passed=False,
        findings=(
            Finding(
                layer="structural",
                check="context_exists",
                severity=Severity.BLOCKING,
                message="missing context",
                trust_class=TrustClass.SYSTEM,
            ),
        ),
        metadata={"executed_check_ids": ("context_exists",)},
    )
    record_qa_layer_artifacts(
        story_dir,
        layer_results=(result,),
        stage_registry=StageRegistry(),
        attempt_nr=1,
        owner_session_id="sqlite-test-owner",
        expected_ownership_epoch=1,
    )
    with _sqlite_connect_qa(story_dir) as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_second_qa_delete
            BEFORE DELETE ON qa_findings
            BEGIN
                SELECT RAISE(ABORT, 'injected second delete failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="second delete failure"):
        build_projection_accessor(story_dir).purge_run("project", "AG3-191", "run-reset-fault")

    assert len(FacadeQAStageResultsRepository(story_dir).read(run_id="run-reset-fault")) == 1
    assert len(FacadeQAFindingsRepository(story_dir).read(run_id="run-reset-fault")) == 1
    assert len(FacadeQACheckOutcomesRepository(story_dir).read(project_key="project", run_id="run-reset-fault")) == 1
    reset_backend_cache_for_tests()


def test_batch_rejects_nonexistent_canonical_artifact_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I4: projection rows cannot point at an absent artifact envelope."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    story_dir = tmp_path / "AG3-191"
    story_dir.mkdir()
    flow = FlowExecution(
        project_key="project",
        story_id="AG3-191",
        run_id="run-missing-envelope",
        flow_id="implementation",
        level="story",
        owner="pipeline-engine",
    )
    save_flow_execution(story_dir, flow)
    result = LayerResult(
        layer="structural",
        passed=True,
        metadata={"executed_check_ids": ()},
    )
    registry = StageRegistry()
    reference = write_qa_layer_envelopes(
        story_dir,
        layer_results=(result,),
        stage_registry=registry,
        attempt_nr=1,
    )["structural"].model_copy(update={"record_key": "absent-envelope"})
    result = replace(result, artifact_reference=reference)
    outcomes = CheckOutcomeEmitter().build_batch(
        flow,
        (result,),
        attempt_no=1,
        stage_registry=registry,
    )

    with pytest.raises(CorruptStateError, match="canonical artifact envelope"):
        build_projection_accessor(story_dir).record_qa_layer_artifacts(
            story_dir,
            layer_results=(result,),
            check_outcomes=outcomes,
            stage_registry=registry,
            attempt_nr=1,
            owner_session_id="sqlite-test-owner",
            expected_ownership_epoch=1,
        )

    assert FacadeQAStageResultsRepository(story_dir).read(run_id="run-missing-envelope") == []
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
    artifact_references = write_qa_layer_envelopes(
        story_dir,
        layer_results=(layer_result,),
        stage_registry=StageRegistry(),
        attempt_nr=1,
    )
    layer_result = replace(
        layer_result,
        artifact_reference=artifact_references[layer_result.layer],
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
    artifact_references = write_qa_layer_envelopes(
        story_dir,
        layer_results=(layer_result,),
        stage_registry=registry,
        attempt_nr=1,
    )
    layer_result = replace(
        layer_result,
        artifact_reference=artifact_references[layer_result.layer],
    )

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
