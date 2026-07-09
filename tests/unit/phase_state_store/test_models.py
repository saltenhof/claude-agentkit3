"""Unit tests for flow-oriented phase-state-store models."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from agentkit.backend.core_types import OverrideType
from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.phase_state_store import (
    FlowExecution,
    NodeExecutionLedger,
    OverrideRecord,
)
from agentkit.backend.state_backend.persistence_mappers import (
    override_record_to_row,
    override_row_to_record,
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
            override_type=OverrideType.SKIP_NODE,
            actor_type="human",
            actor_id="owner",
            reason="known flaky dependency outage",
            created_at=created_at,
        )
        assert record.override_type is OverrideType.SKIP_NODE
        assert record.target_node_id == "qa_review"
        assert record.created_at is created_at

    def test_wire_string_is_normalized_to_enum(self) -> None:
        record = OverrideRecord(
            override_id="ovr-1",
            project_key="proj",
            story_id="ST-1",
            run_id="run-1",
            flow_id="verify",
            target_node_id="qa_review",
            override_type=OverrideType.SKIP_NODE.value,  # type: ignore[arg-type]
            actor_type="human",
            actor_id="owner",
            reason="known flaky dependency outage",
            created_at=datetime.now(tz=UTC),
        )

        assert record.override_type is OverrideType.SKIP_NODE

    def test_mapper_round_trips_override_type_as_text_wire(self) -> None:
        created_at = datetime.now(tz=UTC)
        record = OverrideRecord(
            override_id="ovr-1",
            project_key="proj",
            story_id="ST-1",
            run_id="run-1",
            flow_id="verify",
            target_node_id="qa_review",
            override_type=OverrideType.JUMP_TO,
            actor_type="human",
            actor_id="owner",
            reason="operator jump",
            created_at=created_at,
        )

        row = override_record_to_row(record)
        loaded = override_row_to_record(row)

        assert row["override_type"] == "jump_to"
        assert loaded.override_type is OverrideType.JUMP_TO

    def test_unknown_persisted_override_type_fails_closed(self) -> None:
        row = {
            "override_id": "ovr-bad",
            "project_key": "proj",
            "story_id": "ST-1",
            "run_id": "run-1",
            "flow_id": "verify",
            "target_node_id": "qa_review",
            "override_type": "resume",
            "actor_type": "human",
            "actor_id": "owner",
            "reason": "bad persisted value",
            "created_at": datetime.now(tz=UTC).isoformat(),
            "consumed_at": None,
        }

        with pytest.raises(CorruptStateError, match="unknown value"):
            override_row_to_record(row)
