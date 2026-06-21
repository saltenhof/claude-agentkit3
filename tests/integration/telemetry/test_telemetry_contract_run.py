"""Integration test: a worker run satisfies the TelemetryContract (AG3-037).

Exercises the real path end to end on SQLite:
- a worker run emits ``agent_start``/``agent_end`` + ``review_request``/
  ``review_response``/``review_compliant`` + ``llm_call`` + a complete preflight
  triplet (``preflight_request``/``preflight_response``/``preflight_compliant``)
  via the canonical ``StateBackendEmitter``;
- ``TelemetryContract.check_all`` (over the real ``StateBackendExecutionEventReader``)
  returns PASS;
- the ``EventNormalizer`` writes a ``NormalizedEvent`` into the risk window via
  the real ``ProjectionAccessor`` and a full reset purges it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.store import (
    reset_backend_cache_for_tests,
    save_flow_execution,
    save_story_context,
)
from agentkit.backend.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.contract.results import TelemetryScope
from agentkit.backend.telemetry.contract.telemetry_contract import TelemetryContract
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor
from agentkit.backend.telemetry.risk_window.normalizer import EventNormalizer
from agentkit.backend.telemetry.storage import (
    StateBackendEmitter,
    StateBackendExecutionEventReader,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "demo-project"
_STORY = "AG3-001"
_RUN = "run-int-001"


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _seed_scope(story_dir: Path, tmp_path: Path) -> None:
    save_story_context(
        story_dir,
        StoryContext(
            project_key=_PROJECT,
            story_id=_STORY,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            title="Telemetry contract run",
            project_root=tmp_path / _PROJECT,
        ),
    )
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )


def _emit_complete_run(emitter: StateBackendEmitter) -> None:
    events = [
        Event(story_id=_STORY, event_type=EventType.AGENT_START, run_id=_RUN),
        Event(
            story_id=_STORY,
            event_type=EventType.REVIEW_REQUEST,
            run_id=_RUN,
            payload={"reviewer_role": "qa", "pool": "chatgpt"},  # canonical key (AG3-119)
        ),
        Event(
            story_id=_STORY,
            event_type=EventType.REVIEW_RESPONSE,
            run_id=_RUN,
            payload={"reviewer_role": "qa", "verdict": "PASS"},  # canonical key (AG3-119)
        ),
        Event(
            story_id=_STORY,
            event_type=EventType.REVIEW_COMPLIANT,
            run_id=_RUN,
            payload={"pool": "chatgpt", "template_name": "review-v1"},
        ),
        Event(
            story_id=_STORY,
            event_type=EventType.LLM_CALL,
            run_id=_RUN,
            payload={"role": "qa", "pool": "chatgpt"},
        ),
        Event(
            story_id=_STORY,
            event_type=EventType.PREFLIGHT_REQUEST,
            run_id=_RUN,
            payload={"pool": "chatgpt"},
        ),
        Event(
            story_id=_STORY,
            event_type=EventType.PREFLIGHT_RESPONSE,
            run_id=_RUN,
            payload={"pool": "chatgpt", "request_count": 1},
        ),
        Event(
            story_id=_STORY,
            event_type=EventType.PREFLIGHT_COMPLIANT,
            run_id=_RUN,
            payload={"pool": "chatgpt"},
        ),
        Event(story_id=_STORY, event_type=EventType.AGENT_END, run_id=_RUN),
    ]
    for event in events:
        emitter.emit(event)


def test_complete_worker_run_satisfies_check_all(tmp_path: Path) -> None:
    story_dir = tmp_path / "stories" / _STORY
    story_dir.mkdir(parents=True)
    _seed_scope(story_dir, tmp_path)
    _emit_complete_run(StateBackendEmitter(story_dir))

    reader = StateBackendExecutionEventReader(
        story_dir, project_key=_PROJECT, story_id=_STORY
    )
    scope = TelemetryScope(project_key=_PROJECT, story_id=_STORY, run_id=_RUN)
    contract = TelemetryContract(reader, MemoryEmitter(), scope)
    result = contract.check_all(_RUN, {"qa"}, {"qa": "chatgpt"}, web_call_budget=200)

    assert result.passed, f"Expected PASS, got failures: {result.failures}"
    assert len(result.rule_results) == 6


def test_missing_agent_end_fails_check_all(tmp_path: Path) -> None:
    story_dir = tmp_path / "stories" / _STORY
    story_dir.mkdir(parents=True)
    _seed_scope(story_dir, tmp_path)
    emitter = StateBackendEmitter(story_dir)
    emitter.emit(Event(story_id=_STORY, event_type=EventType.AGENT_START, run_id=_RUN))

    reader = StateBackendExecutionEventReader(
        story_dir, project_key=_PROJECT, story_id=_STORY
    )
    scope = TelemetryScope(project_key=_PROJECT, story_id=_STORY, run_id=_RUN)
    result = TelemetryContract(reader, MemoryEmitter(), scope).check_all(
        _RUN, set(), {}, web_call_budget=200
    )

    assert not result.passed
    assert any(r.rule_id == "FK-68 §68.4.1" for r in result.failures)
    # The crashed run never ran preflight -> fail-closed (FK-68 §68.9.3).
    assert any(r.rule_id == "FK-68 §68.9.2" for r in result.failures)


def test_empty_preflight_stream_persists_violation_via_state_backend(
    tmp_path: Path,
) -> None:
    """FIX-1: an EMPTY stream persists the preflight violation (FK-68 §68.9).

    The most critical case: the run emitted NO preflight events at all. Before
    the fix the sentinel attributed the violation from ``events[0]`` — which does
    not exist on an empty stream — producing ``story_id="unknown"`` /
    ``run_id=None``, so the ``StateBackendEmitter`` dropped the audit event
    (project/run scope missing). With the authoritative ``TelemetryScope`` bound
    to the contract, the violation MUST be persisted to the canonical stream.
    """
    story_dir = tmp_path / "stories" / _STORY
    story_dir.mkdir(parents=True)
    _seed_scope(story_dir, tmp_path)

    # Only an unrelated event exists; the preflight stream is empty.
    real_emitter = StateBackendEmitter(story_dir)
    real_emitter.emit(
        Event(story_id=_STORY, event_type=EventType.AGENT_START, run_id=_RUN)
    )

    reader = StateBackendExecutionEventReader(
        story_dir, project_key=_PROJECT, story_id=_STORY
    )
    scope = TelemetryScope(project_key=_PROJECT, story_id=_STORY, run_id=_RUN)
    contract = TelemetryContract(reader, real_emitter, scope)

    result = contract.check_preflight_compliant_balance(_RUN)
    assert result.status.value == "FAIL"
    assert "PREFLIGHT_MISSING" in result.detail

    # The violation is now durably in the canonical execution-event stream.
    persisted = real_emitter.query(
        _STORY, EventType.PREFLIGHT_COMPLIANCE_VIOLATION
    )
    assert len(persisted) == 1, "empty-stream preflight violation was not persisted"
    violation = persisted[0]
    assert violation.story_id == _STORY
    assert violation.run_id == _RUN
    assert violation.project_key == _PROJECT
    assert violation.payload["preflight_request"] == 0
    assert violation.payload["failure_code"] == "PREFLIGHT_MISSING"


def test_risk_window_write_and_purge_roundtrip(tmp_path: Path) -> None:
    story_dir = tmp_path / "stories" / _STORY
    story_dir.mkdir(parents=True)
    _seed_scope(story_dir, tmp_path)

    accessor: ProjectionAccessor = ProjectionAccessor(
        build_projection_repositories(story_dir)
    )
    normalizer = EventNormalizer(risk_window_writer=accessor)

    record = ExecutionEventRecord(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        event_id="evt-iv-1",
        event_type=EventType.INTEGRITY_VIOLATION.value,
        occurred_at=datetime.now(UTC),
        source_component="prompt_integrity_guard",
        severity="error",
        payload={"guard": "orchestrator_guard", "detail": "blocked", "stage": "x"},
    )
    written = normalizer.normalize_and_record(record)
    assert written is not None

    rows = _read_risk_window(story_dir)
    assert len(rows) == 1
    assert rows[0]["event_id"] == "evt-iv-1"
    assert rows[0]["risk_category"] == "integrity"
    assert rows[0]["project_key"] == _PROJECT

    purged = accessor.purge_run(_PROJECT, _STORY, _RUN)
    assert purged.errors == []
    assert _read_risk_window(story_dir) == []


def _read_risk_window(story_dir: Path) -> list[dict[str, object]]:
    from agentkit.backend.state_backend.store.projection_repositories import _sqlite_connect_qa

    with _sqlite_connect_qa(story_dir) as conn:
        rows = conn.execute("SELECT * FROM risk_window").fetchall()
    return [dict(row) for row in rows]
