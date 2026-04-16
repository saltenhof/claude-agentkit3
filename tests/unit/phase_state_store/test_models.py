"""Unit tests for flow-oriented phase-state-store models."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

from agentkit.phase_state_store import (
    FlowExecution,
    NodeExecutionLedger,
    OverrideRecord,
)


class TestFlowExecution:
    """Tests for flow execution records."""

    def test_defaults(self) -> None:
        record = FlowExecution(
            project_key="proj",
            story_id="ST-1",
            run_id="run-1",
            flow_id="verify",
            level="phase",
            owner="PipelineEngine",
        )
        assert record.status == "READY"
        assert record.attempt_no == 1
        assert record.parent_flow_id is None
        assert record.started_at.tzinfo is UTC

    def test_frozen(self) -> None:
        record = FlowExecution(
            project_key="proj",
            story_id="ST-1",
            run_id="run-1",
            flow_id="verify",
            level="phase",
            owner="PipelineEngine",
        )
        try:
            record.status = "FAILED"  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            pass
        else:  # pragma: no cover - defensive
            raise AssertionError("FlowExecution must be frozen")


class TestNodeExecutionLedger:
    """Tests for per-node execution history records."""

    def test_construction(self) -> None:
        ledger = NodeExecutionLedger(
            project_key="proj",
            story_id="ST-1",
            run_id="run-1",
            flow_id="verify",
            node_id="semantic_review",
            execution_count=2,
            success_count=1,
            last_outcome="FAIL",
            last_attempt_no=2,
        )
        assert ledger.execution_count == 2
        assert ledger.success_count == 1
        assert ledger.last_outcome == "FAIL"


class TestOverrideRecord:
    """Tests for override audit records."""

    def test_construction(self) -> None:
        created_at = datetime.now(tz=UTC)
        record = OverrideRecord(
            override_id="ovr-1",
            project_key="proj",
            story_id="ST-1",
            run_id="run-1",
            flow_id="verify",
            target_node_id="qa_review",
            override_type="skip_node",
            actor_type="human",
            actor_id="owner",
            reason="known flaky dependency outage",
            created_at=created_at,
        )
        assert record.override_type == "skip_node"
        assert record.target_node_id == "qa_review"
        assert record.created_at is created_at
