from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.phase_state_store.models import FlowExecution
from agentkit.qa.policy_engine.engine import VerifyDecision
from agentkit.qa.protocols import Finding, LayerResult, Severity, TrustClass
from agentkit.state_backend import (
    ExecutionEventRecord,
    StoryMetricsRecord,
    append_execution_event,
    append_execution_event_global,
    load_artifact_record,
    load_artifact_record_for_scope,
    load_execution_events,
    load_execution_events_global,
    load_flow_execution,
    load_flow_execution_global,
    load_latest_story_metrics_global,
    load_latest_verify_decision,
    load_latest_verify_decision_for_scope,
    load_phase_snapshot,
    load_phase_state,
    load_phase_state_global,
    load_qa_findings,
    load_qa_stage_results,
    load_story_context,
    load_story_context_global,
    load_story_contexts_global,
    load_story_metrics,
    record_layer_artifacts,
    record_verify_decision,
    resolve_runtime_scope,
    save_flow_execution,
    save_phase_snapshot,
    save_phase_state,
    save_story_context,
    upsert_story_metrics,
)
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.types import StoryMode, StoryType

pytest_plugins = ("tests.fixtures.postgres_backend",)


@pytest.mark.contract
def test_public_state_backend_contract_works_on_postgres(
    tmp_path,
    postgres_backend_env,
) -> None:
    project_root = tmp_path / "demo-project"
    story_dir = project_root / "stories" / "AG3-901"
    story_dir.mkdir(parents=True, exist_ok=True)

    ctx = StoryContext(
        project_key="demo-project",
        story_id="AG3-901",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        title="Postgres contract test",
        project_root=project_root,
        created_at=datetime.now(tz=UTC),
    )
    save_story_context(story_dir, ctx)

    loaded_ctx = load_story_context(story_dir)
    assert loaded_ctx is not None
    assert loaded_ctx.story_id == "AG3-901"
    assert load_story_context_global("demo-project", "AG3-901") is not None
    assert load_story_contexts_global("demo-project")[0].story_id == "AG3-901"

    state = PhaseState(
        story_id="AG3-901",
        phase="verify",
        status=PhaseStatus.IN_PROGRESS,
    )
    save_phase_state(story_dir, state)
    loaded_state = load_phase_state(story_dir)
    assert loaded_state is not None
    assert loaded_state.phase == "verify"
    assert load_phase_state_global("AG3-901") is not None

    snapshot = PhaseSnapshot(
        story_id="AG3-901",
        phase="setup",
        status=PhaseStatus.COMPLETED,
        completed_at=datetime.now(tz=UTC),
        artifacts=["protocol.md"],
        evidence={"kind": "contract"},
    )
    save_phase_snapshot(story_dir, snapshot)
    loaded_snapshot = load_phase_snapshot(story_dir, "setup")
    assert loaded_snapshot is not None
    assert loaded_snapshot.status == PhaseStatus.COMPLETED

    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="demo-project",
            story_id="AG3-901",
            run_id="run-contract-001",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="COMPLETED",
        ),
    )
    loaded_flow = load_flow_execution(story_dir)
    assert loaded_flow is not None
    assert loaded_flow.run_id == "run-contract-001"
    assert load_flow_execution_global("demo-project", "AG3-901") is not None
    run1_scope = resolve_runtime_scope(story_dir)
    assert run1_scope.run_id == "run-contract-001"

    produced = record_layer_artifacts(
        story_dir,
        layer_results=(
            LayerResult(
                layer="structural",
                passed=False,
                findings=(
                    Finding(
                        layer="structural",
                        check="context_exists",
                        severity=Severity.CRITICAL,
                        message="context.json is missing",
                        trust_class=TrustClass.SYSTEM,
                        file_path="context.json",
                        line_number=1,
                    ),
                    Finding(
                        layer="structural",
                        check="lint",
                        severity=Severity.MEDIUM,
                        message="style drift",
                        trust_class=TrustClass.SYSTEM,
                        file_path="src/app.py",
                        line_number=10,
                    ),
                ),
                metadata={"source": "contract", "total_checks": 7},
            ),
        ),
        attempt_nr=1,
    )
    assert produced == ("structural.json",)
    structural_record = load_artifact_record(story_dir, "structural")
    assert structural_record is not None
    assert structural_record["layer"] == "structural"
    stage_results = load_qa_stage_results(
        story_dir,
        project_key="demo-project",
        story_id="AG3-901",
        run_id="run-contract-001",
        attempt_no=1,
        stage_id="structural",
    )
    assert len(stage_results) == 1
    assert stage_results[0].status == "FAIL"
    assert stage_results[0].total_checks == 7
    assert stage_results[0].failed_checks == 1
    assert stage_results[0].warning_checks == 1

    findings = load_qa_findings(
        story_dir,
        project_key="demo-project",
        story_id="AG3-901",
        run_id="run-contract-001",
        attempt_no=1,
        stage_id="structural",
    )
    assert len(findings) == 2
    assert findings[0].status == "REPORTED"
    assert findings[0].artifact_id == "structural-attempt-1"
    assert {finding.severity for finding in findings} == {"critical", "medium"}

    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="demo-project",
            story_id="AG3-901",
            run_id="run-contract-002",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="COMPLETED",
        ),
    )
    run2_scope = resolve_runtime_scope(story_dir)
    assert run2_scope.run_id == "run-contract-002"
    record_layer_artifacts(
        story_dir,
        layer_results=(
            LayerResult(
                layer="structural",
                passed=True,
                findings=(),
            ),
        ),
        attempt_nr=1,
    )
    run2_record = load_artifact_record(story_dir, "structural")
    assert run2_record is not None
    assert run2_record["passed"] is True
    run2_record_scoped = load_artifact_record_for_scope(run2_scope, "structural")
    assert run2_record_scoped is not None
    assert run2_record_scoped["passed"] is True
    record_verify_decision(
        story_dir,
        decision=VerifyDecision(
            passed=False,
            status="FAIL",
            layer_results=(LayerResult(layer="structural", passed=False),),
            all_findings=(),
            blocking_findings=(),
            summary="run2 failed",
        ),
        attempt_nr=1,
    )
    run2_decision = load_latest_verify_decision(story_dir)
    assert run2_decision is not None
    assert run2_decision["status"] == "FAIL"
    run2_decision_scoped = load_latest_verify_decision_for_scope(run2_scope)
    assert run2_decision_scoped is not None
    assert run2_decision_scoped["status"] == "FAIL"

    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="demo-project",
            story_id="AG3-901",
            run_id="run-contract-001",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="COMPLETED",
        ),
    )
    run1_record = load_artifact_record(story_dir, "structural")
    assert run1_record is not None
    assert run1_record["passed"] is False
    run1_record_scoped = load_artifact_record_for_scope(run1_scope, "structural")
    assert run1_record_scoped is not None
    assert run1_record_scoped["passed"] is False

    record_layer_artifacts(
        story_dir,
        layer_results=(
            LayerResult(
                layer="structural",
                passed=False,
                findings=(
                    Finding(
                        layer="structural",
                        check="context_exists",
                        severity=Severity.CRITICAL,
                        message="context.json is still missing",
                        trust_class=TrustClass.SYSTEM,
                        file_path="context.json",
                        line_number=1,
                    ),
                ),
            ),
        ),
        attempt_nr=1,
    )
    rematerialized_findings = load_qa_findings(
        story_dir,
        project_key="demo-project",
        story_id="AG3-901",
        run_id="run-contract-001",
        attempt_no=1,
        stage_id="structural",
    )
    assert len(rematerialized_findings) == 1

    decision = VerifyDecision(
        passed=True,
        status="PASS",
        layer_results=(
            LayerResult(
                layer="structural",
                passed=True,
                metadata={"source": "contract"},
            ),
        ),
        all_findings=(),
        blocking_findings=(),
        summary="postgres ok",
    )
    written = record_verify_decision(
        story_dir,
        decision=decision,
        attempt_nr=1,
    )
    assert written == ("verify-decision.json",)
    verify_record = load_latest_verify_decision(story_dir)
    assert verify_record is not None
    assert verify_record["status"] == "PASS"

    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="demo-project",
            story_id="AG3-901",
            run_id="run-contract-002",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="COMPLETED",
        ),
    )
    verify_record_run2 = load_latest_verify_decision(story_dir)
    assert verify_record_run2 is not None
    assert verify_record_run2["status"] == "FAIL"

    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="demo-project",
            story_id="AG3-901",
            run_id="run-contract-001",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="COMPLETED",
        ),
    )
    verify_record_run1 = load_latest_verify_decision(story_dir)
    assert verify_record_run1 is not None
    assert verify_record_run1["status"] == "PASS"
    verify_record_run1_scoped = load_latest_verify_decision_for_scope(run1_scope)
    assert verify_record_run1_scoped is not None
    assert verify_record_run1_scoped["status"] == "PASS"
    verify_record_run2_scoped = load_latest_verify_decision_for_scope(run2_scope)
    assert verify_record_run2_scoped is not None
    assert verify_record_run2_scoped["status"] == "FAIL"

    append_execution_event(
        story_dir,
        ExecutionEventRecord(
            project_key="demo-project",
            story_id="AG3-901",
            run_id="run-contract-001",
            event_id="evt-contract-001",
            event_type="flow_start",
            occurred_at=datetime.now(tz=UTC),
            source_component="contract-test",
            severity="info",
            flow_id="implementation",
            node_id="setup",
            payload={"kind": "contract"},
        ),
    )
    events = load_execution_events(
        story_dir,
        project_key="demo-project",
        story_id="AG3-901",
        run_id="run-contract-001",
    )
    assert len(events) == 1
    assert events[0].event_type == "flow_start"
    assert events[0].source_component == "contract-test"

    append_execution_event_global(
        ExecutionEventRecord(
            project_key="demo-project",
            story_id="AG3-901",
            run_id="run-contract-001",
            event_id="evt-contract-002",
            event_type="agent_start",
            occurred_at=datetime.now(tz=UTC),
            source_component="control-plane",
            severity="info",
            phase="implementation",
            flow_id="implementation",
            node_id="implementation",
            payload={"channel": "rest"},
        ),
    )
    global_events = load_execution_events(
        story_dir,
        project_key="demo-project",
        story_id="AG3-901",
        run_id="run-contract-001",
        event_type="agent_start",
    )
    assert len(global_events) == 1
    assert global_events[0].event_id == "evt-contract-002"
    assert global_events[0].source_component == "control-plane"
    global_story_events = load_execution_events_global(
        "demo-project",
        "AG3-901",
        run_id="run-contract-001",
        event_type="agent_start",
        limit=10,
    )
    assert len(global_story_events) == 1
    assert global_story_events[0].event_id == "evt-contract-002"

    upsert_story_metrics(
        story_dir,
        StoryMetricsRecord(
            project_key="demo-project",
            story_id="AG3-901",
            run_id="run-contract-001",
            story_type="implementation",
            story_size="medium",
            mode="execution",
            processing_time_min=12.5,
            qa_rounds=2,
            increments=3,
            final_status="completed",
            completed_at="2026-04-20T10:00:00+00:00",
        ),
    )
    metrics = load_story_metrics(
        story_dir,
        project_key="demo-project",
        story_id="AG3-901",
        run_id="run-contract-001",
    )
    assert len(metrics) == 1
    assert metrics[0].qa_rounds == 2
    assert metrics[0].increments == 3
    latest_metrics = load_latest_story_metrics_global("demo-project", "AG3-901")
    assert latest_metrics is not None
    assert latest_metrics.run_id == "run-contract-001"
