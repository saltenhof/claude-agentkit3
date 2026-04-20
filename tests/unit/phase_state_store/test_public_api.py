"""Unit tests for phase-state-store public exports."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import agentkit.phase_state_store as phase_state_store_api
import agentkit.state_backend as state_backend
from agentkit.phase_state_store import (
    FlowExecution,
    NodeExecutionLedger,
    OverrideRecord,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_load_override_records_delegates_to_state_backend(tmp_path: Path) -> None:
    expected = [
        OverrideRecord(
            override_id="ovr-1",
            project_key="proj",
            story_id="TEST-001",
            run_id="run-1",
            flow_id="verify",
            target_node_id="qa-review",
            override_type="skip_node",
            actor_type="human",
            actor_id="owner",
            reason="known issue",
            created_at=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
        )
    ]
    seen: list[Path] = []

    def fake_loader(story_dir: Path) -> list[OverrideRecord]:
        seen.append(story_dir)
        return expected

    original = state_backend.load_override_records
    state_backend.load_override_records = fake_loader
    try:
        assert phase_state_store_api.load_override_records(tmp_path) == expected
    finally:
        state_backend.load_override_records = original

    assert seen == [tmp_path]


def test_save_node_execution_ledger_delegates_to_state_backend(tmp_path: Path) -> None:
    record = NodeExecutionLedger(
        project_key="proj",
        story_id="TEST-001",
        run_id="run-1",
        flow_id="verify",
        node_id="semantic_review",
        execution_count=2,
        success_count=1,
        last_outcome="FAIL",
        last_attempt_no=2,
    )
    seen: list[tuple[Path, NodeExecutionLedger]] = []

    def fake_saver(story_dir: Path, ledger: NodeExecutionLedger) -> None:
        seen.append((story_dir, ledger))

    original = state_backend.save_node_execution_ledger
    state_backend.save_node_execution_ledger = fake_saver
    try:
        phase_state_store_api.save_node_execution_ledger(tmp_path, record)
    finally:
        state_backend.save_node_execution_ledger = original

    assert seen == [(tmp_path, record)]


def test_load_flow_execution_delegates_to_state_backend(tmp_path: Path) -> None:
    expected = FlowExecution(
        project_key="proj",
        story_id="TEST-001",
        run_id="run-1",
        flow_id="verify",
        level="phase",
        owner="PipelineEngine",
    )
    seen: list[Path] = []

    def fake_loader(story_dir: Path) -> FlowExecution:
        seen.append(story_dir)
        return expected

    original = state_backend.load_flow_execution
    state_backend.load_flow_execution = fake_loader
    try:
        assert phase_state_store_api.load_flow_execution(tmp_path) == expected
    finally:
        state_backend.load_flow_execution = original

    assert seen == [tmp_path]


def test_save_override_record_delegates_to_state_backend(tmp_path: Path) -> None:
    record = OverrideRecord(
        override_id="ovr-2",
        project_key="proj",
        story_id="TEST-001",
        run_id="run-1",
        flow_id="verify",
        target_node_id=None,
        override_type="resume",
        actor_type="system",
        actor_id="orchestrator",
        reason="retry window open",
        created_at=datetime(2026, 4, 19, 12, 5, 0, tzinfo=UTC),
    )
    seen: list[tuple[Path, OverrideRecord]] = []

    def fake_saver(story_dir: Path, override: OverrideRecord) -> None:
        seen.append((story_dir, override))

    original = state_backend.save_override_record
    state_backend.save_override_record = fake_saver
    try:
        phase_state_store_api.save_override_record(tmp_path, record)
    finally:
        state_backend.save_override_record = original

    assert seen == [(tmp_path, record)]
