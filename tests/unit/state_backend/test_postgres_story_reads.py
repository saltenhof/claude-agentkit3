"""Unit tests for postgres global-read functions via the store facade.

Tests monkeypatch ``postgres_store._connect_global`` to inject fake row data
and then verify the full mapping chain (driver row → mapper → BC-Record) by
calling the public facade functions.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.pipeline_engine.phase_executor import PhaseState
from agentkit.backend.state_backend import postgres_store
from agentkit.backend.state_backend.store import facade
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

if TYPE_CHECKING:
    from collections.abc import Generator


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def execute(self, query: str, params: object = ()) -> _FakeResult:
        return _FakeResult(self.rows)


@contextmanager
def _fake_global(rows: list[Any]) -> Generator[_FakeConnection, None, None]:
    yield _FakeConnection(rows)


@pytest.fixture(autouse=True)
def _use_postgres_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Force postgres backend and clear the facade LRU cache for every test.

    The cache is also cleared on teardown so subsequent tests (which rely on
    AGENTKIT_STATE_BACKEND=sqlite) are not contaminated by the postgres module
    remaining in the LRU cache after monkeypatch reverts the env var.
    """
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "postgres")
    facade.reset_backend_cache_for_tests()
    yield
    # Teardown: clear cache so next test gets the correct backend (sqlite).
    facade.reset_backend_cache_for_tests()


def test_load_story_context_global_reads_single_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        postgres_store,
        "_connect_global",
        lambda: _fake_global(
            [
                {
                    "payload_json": (
                        '{"project_key":"tenant-a","story_id":"AG3-100",'
                        '"story_type":"implementation","execution_route":"execution",'
                        '"title":"Story 100","story_size":"M"}'
                    ),
                },
            ],
        ),
    )

    record = facade.load_story_context_global("tenant-a", "AG3-100")

    assert isinstance(record, StoryContext)
    assert record.story_id == "AG3-100"
    assert record.title == "Story 100"


def test_load_story_contexts_global_reads_multiple_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        postgres_store,
        "_connect_global",
        lambda: _fake_global(
            [
                {
                    "payload_json": (
                        '{"project_key":"tenant-a","story_id":"AG3-100",'
                        '"story_type":"implementation","execution_route":"execution",'
                        '"title":"Story 100","story_size":"S"}'
                    ),
                },
                {
                    "payload_json": (
                        '{"project_key":"tenant-a","story_id":"AG3-101",'
                        '"story_type":"bugfix","execution_route":"execution",'
                        '"title":"Story 101","story_size":"M"}'
                    ),
                },
            ],
        ),
    )

    records = facade.load_story_contexts_global("tenant-a")

    assert [record.story_id for record in records] == ["AG3-100", "AG3-101"]


def test_load_phase_state_global_reads_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload_json = make_phase_state(
        story_id="AG3-100",
        phase="implementation",
        status="in_progress",
        review_round=0,
        errors=[],
    ).model_dump_json()
    monkeypatch.setattr(
        postgres_store,
        "_connect_global",
        lambda: _fake_global(
            [
                {
                    "payload_json": payload_json,
                },
            ],
        ),
    )

    record = facade.load_phase_state_global("AG3-100")

    assert isinstance(record, PhaseState)
    assert record.phase == "implementation"


def test_load_flow_execution_global_reads_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        postgres_store,
        "_connect_global",
        lambda: _fake_global(
            [
                {
                    "project_key": "tenant-a",
                    "story_id": "AG3-100",
                    "run_id": "run-100",
                    "flow_id": "implementation",
                    "level": "story",
                    "owner": "pipeline_engine",
                    "parent_flow_id": None,
                    "status": "RUNNING",
                    "current_node_id": "implementation",
                    "attempt_no": 2,
                    "started_at": "2026-04-22T10:00:00+00:00",
                    "finished_at": None,
                },
            ],
        ),
    )

    record = facade.load_flow_execution_global("tenant-a", "AG3-100")

    assert isinstance(record, FlowExecution)
    assert record.run_id == "run-100"
    assert record.status == "RUNNING"


def test_load_latest_story_metrics_global_reads_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        postgres_store,
        "_connect_global",
        lambda: _fake_global(
            [
                {
                    "project_key": "tenant-a",
                    "story_id": "AG3-100",
                    "run_id": "run-100",
                    "story_type": "implementation",
                    "story_size": "medium",
                    "mode": "standard",
                    "processing_time_min": 12.5,
                    "qa_rounds": 2,
                    "increments": 3,
                    "final_status": "DONE",
                    "completed_at": "2026-04-22T10:30:00+00:00",
                    "adversarial_findings": None,
                    "adversarial_tests_created": None,
                    "files_changed": None,
                    "agentkit_version": None,
                    "agentkit_commit": None,
                    "config_version": None,
                    "llm_roles_json": "[]",
                },
            ],
        ),
    )

    record = facade.load_latest_story_metrics_global("tenant-a", "AG3-100")

    assert isinstance(record, StoryMetricsRecord)
    assert record.final_status == "DONE"


def test_load_execution_events_global_reads_latest_subset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        postgres_store,
        "_connect_global",
        lambda: _fake_global(
            [
                {
                    "project_key": "tenant-a",
                    "story_id": "AG3-100",
                    "run_id": "run-100",
                    "event_id": "evt-002",
                    "event_type": "node_result",
                    "occurred_at": "2026-04-22T10:05:00+00:00",
                    "source_component": "pipeline-engine",
                    "severity": "info",
                    "phase": "implementation",
                    "flow_id": "implementation",
                    "node_id": "node-2",
                    "payload_json": "{\"order\":2}",
                },
                {
                    "project_key": "tenant-a",
                    "story_id": "AG3-100",
                    "run_id": "run-100",
                    "event_id": "evt-001",
                    "event_type": "agent_start",
                    "occurred_at": "2026-04-22T10:00:00+00:00",
                    "source_component": "control-plane",
                    "severity": "info",
                    "phase": "implementation",
                    "flow_id": "implementation",
                    "node_id": "node-1",
                    "payload_json": "{\"order\":1}",
                },
            ],
        ),
    )

    records = facade.load_execution_events_global(
        "tenant-a",
        "AG3-100",
        run_id="run-100",
        limit=2,
    )

    assert all(isinstance(record, ExecutionEventRecord) for record in records)
    assert [record.event_id for record in records] == ["evt-001", "evt-002"]
    assert records[0].occurred_at == datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
