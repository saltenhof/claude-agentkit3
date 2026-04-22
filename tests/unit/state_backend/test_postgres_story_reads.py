from __future__ import annotations

from contextlib import contextmanager

from agentkit.phase_state_store.models import FlowExecution
from agentkit.state_backend import postgres_store
from agentkit.state_backend.records import StoryMetricsRecord
from agentkit.story_context_manager.models import PhaseState, StoryContext


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query: str, params=()):
        return _FakeResult(self.rows)


@contextmanager
def _fake_global(rows):
    yield _FakeConnection(rows)


def test_load_story_context_global_reads_single_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        postgres_store,
        "_connect_global",
        lambda: _fake_global(
            [
                {
                    "payload_json": (
                        '{"project_key":"tenant-a","story_id":"AG3-100",'
                        '"story_type":"implementation","execution_route":"execution",'
                        '"title":"Story 100","story_size":"medium"}'
                    ),
                },
            ],
        ),
    )

    record = postgres_store.load_story_context_global("tenant-a", "AG3-100")

    assert isinstance(record, StoryContext)
    assert record.story_id == "AG3-100"
    assert record.title == "Story 100"


def test_load_story_contexts_global_reads_multiple_payloads(monkeypatch) -> None:
    monkeypatch.setattr(
        postgres_store,
        "_connect_global",
        lambda: _fake_global(
            [
                {
                    "payload_json": (
                        '{"project_key":"tenant-a","story_id":"AG3-100",'
                        '"story_type":"implementation","execution_route":"execution",'
                        '"title":"Story 100","story_size":"small"}'
                    ),
                },
                {
                    "payload_json": (
                        '{"project_key":"tenant-a","story_id":"AG3-101",'
                        '"story_type":"bugfix","execution_route":"execution",'
                        '"title":"Story 101","story_size":"medium"}'
                    ),
                },
            ],
        ),
    )

    records = postgres_store.load_story_contexts_global("tenant-a")

    assert [record.story_id for record in records] == ["AG3-100", "AG3-101"]


def test_load_phase_state_global_reads_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        postgres_store,
        "_connect_global",
        lambda: _fake_global(
            [
                {
                    "payload_json": (
                        '{"story_id":"AG3-100","phase":"implementation",'
                        '"status":"in_progress","review_round":0,"errors":[]}'
                    ),
                },
            ],
        ),
    )

    record = postgres_store.load_phase_state_global("AG3-100")

    assert isinstance(record, PhaseState)
    assert record.phase == "implementation"


def test_load_flow_execution_global_reads_row(monkeypatch) -> None:
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

    record = postgres_store.load_flow_execution_global("tenant-a", "AG3-100")

    assert isinstance(record, FlowExecution)
    assert record.run_id == "run-100"
    assert record.status == "RUNNING"


def test_load_latest_story_metrics_global_reads_row(monkeypatch) -> None:
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
                    "mode": "execution",
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

    record = postgres_store.load_latest_story_metrics_global("tenant-a", "AG3-100")

    assert isinstance(record, StoryMetricsRecord)
    assert record.final_status == "DONE"
