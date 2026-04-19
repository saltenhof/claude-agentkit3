from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.phase_state_store.models import FlowExecution
from agentkit.qa.policy_engine.engine import VerifyDecision
from agentkit.qa.protocols import LayerResult
from agentkit.state_backend import (
    load_artifact_record,
    load_flow_execution,
    load_latest_verify_decision,
    load_phase_snapshot,
    load_phase_state,
    load_story_context,
    record_layer_artifacts,
    record_verify_decision,
    save_flow_execution,
    save_phase_snapshot,
    save_phase_state,
    save_story_context,
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
        story_id="AG3-901",
        story_type=StoryType.IMPLEMENTATION,
        mode=StoryMode.EXECUTION,
        title="Postgres contract test",
        project_root=project_root,
        created_at=datetime.now(tz=UTC),
    )
    save_story_context(story_dir, ctx)

    loaded_ctx = load_story_context(story_dir)
    assert loaded_ctx is not None
    assert loaded_ctx.story_id == "AG3-901"

    state = PhaseState(
        story_id="AG3-901",
        phase="verify",
        status=PhaseStatus.IN_PROGRESS,
    )
    save_phase_state(story_dir, state)
    loaded_state = load_phase_state(story_dir)
    assert loaded_state is not None
    assert loaded_state.phase == "verify"

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

    produced = record_layer_artifacts(
        story_dir,
        layer_results=(
            LayerResult(
                layer="structural",
                passed=True,
                metadata={"source": "contract"},
            ),
        ),
        attempt_nr=1,
    )
    assert produced == ("structural.json",)
    structural_record = load_artifact_record(story_dir, "structural")
    assert structural_record is not None
    assert structural_record["layer"] == "structural"

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
    assert written == ("verify-decision.json", "decision.json")
    verify_record = load_latest_verify_decision(story_dir)
    assert verify_record is not None
    assert verify_record["status"] == "PASS"
