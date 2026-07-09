"""AG3-126 AC2: StateBackendStoryReadRepository against the real backend chain.

Drives the productive ``StoryReadPort`` adapter through the REAL
facade → ``postgres_store`` → mapper chain (the psycopg connection is the only
stubbed boundary, mirroring ``test_postgres_story_reads``). This proves the
adapter returns the correct StoryContext/PhaseState/FlowExecution/StoryMetrics/
``execution_events`` records — not just a structural ``runtime_checkable`` match
(which is asserted additionally).
"""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.pipeline_engine.phase_executor import PhaseState
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.postgres_store import (
    _qa_artifact_rows,
    _runtime_rows,
    _story_project_rows,
)
from agentkit.backend.state_backend.store.story_read_repository import (
    StateBackendStoryReadRepository,
)
from agentkit.backend.story.repository import StoryReadPort
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
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "postgres")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _seed(monkeypatch: pytest.MonkeyPatch, rows: list[Any]) -> None:
    def fake() -> AbstractContextManager[_FakeConnection]:
        return _fake_global(rows)

    monkeypatch.setattr(_story_project_rows, "_connect_global", fake)
    monkeypatch.setattr(_runtime_rows, "_connect_global", fake)
    monkeypatch.setattr(_qa_artifact_rows, "_connect_global", fake)


def test_adapter_is_runtime_checkable_story_read_port() -> None:
    assert isinstance(StateBackendStoryReadRepository(), StoryReadPort)


def test_adapter_reads_story_contexts(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(
        monkeypatch,
        [
            {
                "payload_json": (
                    '{"project_key":"tenant-a","story_id":"AG3-100",'
                    '"story_type":"implementation","execution_route":"execution",'
                    '"title":"Story 100","story_size":"S"}'
                ),
            },
        ],
    )
    contexts = StateBackendStoryReadRepository().list_story_contexts("tenant-a")
    assert [c.story_id for c in contexts] == ["AG3-100"]
    assert isinstance(contexts[0], StoryContext)


def test_adapter_reads_story_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(
        monkeypatch,
        [
            {
                "payload_json": (
                    '{"project_key":"tenant-a","story_id":"AG3-100",'
                    '"story_type":"implementation","execution_route":"execution",'
                    '"title":"Story 100","story_size":"M"}'
                ),
            },
        ],
    )
    record = StateBackendStoryReadRepository().load_story_context("tenant-a", "AG3-100")
    assert isinstance(record, StoryContext)
    assert record.title == "Story 100"


def test_adapter_reads_phase_state(monkeypatch: pytest.MonkeyPatch) -> None:
    payload_json = make_phase_state(
        story_id="AG3-100",
        phase="implementation",
        status="in_progress",
        review_round=0,
        errors=[],
    ).model_dump_json()
    _seed(monkeypatch, [{"payload_json": payload_json}])
    record = StateBackendStoryReadRepository().load_phase_state("AG3-100")
    assert isinstance(record, PhaseState)
    assert record.phase == "implementation"


def test_adapter_reads_flow_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(
        monkeypatch,
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
    )
    record = StateBackendStoryReadRepository().load_flow_execution("tenant-a", "AG3-100")
    assert isinstance(record, FlowExecution)
    assert record.run_id == "run-100"
    assert record.status == "RUNNING"


def test_adapter_reads_latest_story_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(
        monkeypatch,
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
    )
    record = StateBackendStoryReadRepository().load_latest_story_metrics(
        "tenant-a", "AG3-100"
    )
    assert isinstance(record, StoryMetricsRecord)
    assert record.final_status == "DONE"


def test_adapter_reads_recent_execution_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(
        monkeypatch,
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
                "payload_json": '{"order":2}',
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
                "payload_json": '{"order":1}',
            },
        ],
    )
    records = StateBackendStoryReadRepository().load_recent_execution_events(
        "tenant-a", "AG3-100", "run-100", 25
    )
    assert all(isinstance(r, ExecutionEventRecord) for r in records)
    assert [r.event_id for r in records] == ["evt-001", "evt-002"]
    assert records[0].occurred_at == datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
