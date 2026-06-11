"""Unit tests for the productive ``StateBackendAnalyticsSource`` (AG3-082, FIX 1/2/4).

The adapter is the productive ``AnalyticsSourcePort`` the composition root injects
into the real ``RefreshWorker``. These tests exercise each method over the real
SQLite-backed ``ProjectionAccessor`` (story/corpus/pipeline read-models + the
run-scoped ``purge_run``) and over an injected event-facade for the event-driven
methods (watermark/delta/pool/guard) — the §5 MOCKS-AUSNAHME boundary, since the
project-global event stream is Postgres-canonical (FK-60 §60.3.2) and the
Docker-free harness has no global SQLite event store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.state_backend.store.analytics_source import StateBackendAnalyticsSource
from agentkit.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.telemetry.contract.records import ExecutionEventRecord
from agentkit.telemetry.events import EventType
from agentkit.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PROJECT = "tenant-s"
_NOW = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
_WEEK = "2026-06-08"  # ISO week of 2026-06-11 (Thursday)


@pytest.fixture(autouse=True)
def _pin_sqlite(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _accessor(tmp_path: Path) -> ProjectionAccessor:
    return ProjectionAccessor(build_projection_repositories(tmp_path))


def _seed_metrics(
    accessor: ProjectionAccessor,
    *,
    story_id: str,
    completed_at: str,
    final_status: str = "DONE",
    qa_rounds: int = 2,
) -> None:
    accessor.write_projection(
        ProjectionKind.STORY_METRICS,
        StoryMetricsRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=f"run-{story_id}",
            story_type="implementation",
            story_size="M",
            mode="execution",
            processing_time_min=10.0,
            qa_rounds=qa_rounds,
            increments=2,
            final_status=final_status,
            completed_at=completed_at,
            files_changed=3,
            agentkit_version="3.20.0",
            agentkit_commit="abc",
        ),
    )


def _event(
    event_id: str,
    *,
    event_type: str,
    occurred_at: datetime = _NOW,
    pool_key: str | None = None,
    guard_key: str | None = None,
    story_id: str = "AG3-300",
) -> ExecutionEventRecord:
    payload: dict[str, object] = {}
    if pool_key is not None:
        payload["pool_key"] = pool_key
    if guard_key is not None:
        payload["guard_key"] = guard_key
    return ExecutionEventRecord(
        project_key=_PROJECT,
        story_id=story_id,
        run_id="run-1",
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        source_component="test",
        severity="info",
        payload=payload,
    )


def _source_with_events(
    accessor: ProjectionAccessor,
    monkeypatch: pytest.MonkeyPatch,
    events: list[ExecutionEventRecord],
) -> StateBackendAnalyticsSource:
    source = StateBackendAnalyticsSource(accessor, project_key=_PROJECT)
    monkeypatch.setattr(
        source, "_load_project_events", lambda project_key: list(events)
    )
    return source


# ---------------------------------------------------------------------------
# story read-models
# ---------------------------------------------------------------------------


def test_recompute_fact_story_maps_metrics(tmp_path: Path) -> None:
    accessor = _accessor(tmp_path)
    _seed_metrics(accessor, story_id="AG3-300", completed_at=_NOW.isoformat())
    source = StateBackendAnalyticsSource(accessor, project_key=_PROJECT)

    fact = source.recompute_fact_story(_PROJECT, "AG3-300")

    assert fact is not None
    assert fact.story_id == "AG3-300"
    assert fact.story_type == "implementation"
    assert fact.qa_rounds == 2
    assert fact.completed_at == _NOW


def test_recompute_fact_story_none_for_open_story(tmp_path: Path) -> None:
    source = StateBackendAnalyticsSource(_accessor(tmp_path), project_key=_PROJECT)
    assert source.recompute_fact_story(_PROJECT, "UNKNOWN") is None


def test_get_story_closed_at_returns_metrics_completed_at(tmp_path: Path) -> None:
    accessor = _accessor(tmp_path)
    _seed_metrics(accessor, story_id="AG3-300", completed_at=_NOW.isoformat())
    source = StateBackendAnalyticsSource(accessor, project_key=_PROJECT)

    assert source.get_story_closed_at(_PROJECT, "AG3-300") == _NOW


def test_get_story_closed_at_none_for_missing_metrics(tmp_path: Path) -> None:
    source = StateBackendAnalyticsSource(_accessor(tmp_path), project_key=_PROJECT)
    assert source.get_story_closed_at(_PROJECT, "UNKNOWN") is None


# ---------------------------------------------------------------------------
# period recomputes from read-models (SQLite-capable)
# ---------------------------------------------------------------------------


def test_recompute_fact_pipeline_period_from_story_metrics(tmp_path: Path) -> None:
    accessor = _accessor(tmp_path)
    # Two completed + one escalated in week 2026-06-08; one in a different week.
    _seed_metrics(accessor, story_id="A", completed_at=_NOW.isoformat(), qa_rounds=2)
    _seed_metrics(accessor, story_id="B", completed_at=_NOW.isoformat(), qa_rounds=4)
    _seed_metrics(
        accessor,
        story_id="C",
        completed_at=_NOW.isoformat(),
        final_status="ESCALATED",
        qa_rounds=6,
    )
    _seed_metrics(
        accessor,
        story_id="D",
        completed_at=datetime(2026, 5, 1, tzinfo=UTC).isoformat(),
    )
    source = StateBackendAnalyticsSource(accessor, project_key=_PROJECT)

    row = source.recompute_fact_pipeline_period(_PROJECT, _WEEK)

    assert row.stories_completed == 2  # A, B (C is escalated)
    assert row.stories_escalated == 1  # C
    assert row.avg_qa_rounds == pytest.approx((2 + 4 + 6) / 3)


def test_recompute_fact_corpus_period_empty(tmp_path: Path) -> None:
    source = StateBackendAnalyticsSource(_accessor(tmp_path), project_key=_PROJECT)

    row = source.recompute_fact_corpus_period(_PROJECT, "2026-06-01")

    assert row.incidents_recorded == 0
    assert row.period_start == datetime(2026, 6, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# event-driven methods (watermark / delta / pool / guard)
# ---------------------------------------------------------------------------


def test_get_watermark_returns_last_event_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        _event("evt-1", event_type=EventType.AGENT_START.value),
        _event("evt-2", event_type=EventType.AGENT_END.value),
    ]
    source = _source_with_events(_accessor(tmp_path), monkeypatch, events)

    assert source.get_watermark(_PROJECT) == "evt-2"


def test_get_watermark_none_when_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source_with_events(_accessor(tmp_path), monkeypatch, [])
    assert source.get_watermark(_PROJECT) is None


def test_read_delta_events_respects_cursor_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        _event("evt-1", event_type=EventType.AGENT_START.value),
        _event("evt-2", event_type=EventType.LLM_CALL.value, pool_key="qa"),
        _event("evt-3", event_type=EventType.AGENT_END.value),
    ]
    source = _source_with_events(_accessor(tmp_path), monkeypatch, events)

    delta = source.read_delta_events(
        _PROJECT, after_event_id="evt-1", through_event_id="evt-2"
    )

    assert [d.event_id for d in delta] == ["evt-2"]
    assert delta[0].pool_key == "qa"  # payload classification


def test_recompute_fact_pool_period_counts_pool_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        _event("evt-1", event_type=EventType.LLM_CALL.value, pool_key="qa"),
        _event("evt-2", event_type=EventType.REVIEW_RESPONSE.value, pool_key="qa"),
        _event("evt-3", event_type=EventType.LLM_CALL.value, pool_key="review"),
    ]
    source = _source_with_events(_accessor(tmp_path), monkeypatch, events)

    row = source.recompute_fact_pool_period(_PROJECT, "qa", _WEEK)

    assert row.llm_role == "qa"
    assert row.call_count == 2  # two qa-pool events in the week


def test_recompute_fact_guard_period_counts_violation_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        _event(
            "evt-1",
            event_type=EventType.INTEGRITY_VIOLATION.value,
            guard_key="orchestrator_guard",
        ),
        _event(
            "evt-2",
            event_type=EventType.INTEGRITY_VIOLATION.value,
            guard_key="orchestrator_guard",
        ),
        _event(
            "evt-3",
            event_type=EventType.INTEGRITY_VIOLATION.value,
            guard_key="other_guard",
        ),
    ]
    source = _source_with_events(_accessor(tmp_path), monkeypatch, events)

    row = source.recompute_fact_guard_period(_PROJECT, "orchestrator_guard", _WEEK)

    assert row.guard_id == "orchestrator_guard"
    assert row.invocation_count == 2
    assert row.violation_count == 2


# ---------------------------------------------------------------------------
# reset purge consumes the REAL run-scoped purge_run (FIX 2)
# ---------------------------------------------------------------------------


def test_purge_run_read_models_delegates_to_accessor_purge_run(
    tmp_path: Path,
) -> None:
    accessor = _accessor(tmp_path)
    _seed_metrics(accessor, story_id="AG3-300", completed_at=_NOW.isoformat())
    source = StateBackendAnalyticsSource(accessor, project_key=_PROJECT)

    # Pre-condition: the run-bound story_metrics row exists.
    assert (
        len(
            accessor.read_projection(
                ProjectionKind.STORY_METRICS,
                ProjectionFilter(
                    project_key=_PROJECT, story_id="AG3-300", run_id="run-AG3-300"
                ),
            )
        )
        == 1
    )

    purged = source.purge_run_read_models(_PROJECT, "AG3-300", "run-AG3-300")

    # The REAL purge_run removed the run-bound FK-69 read model.
    assert purged >= 1
    assert (
        accessor.read_projection(
            ProjectionKind.STORY_METRICS,
            ProjectionFilter(
                project_key=_PROJECT, story_id="AG3-300", run_id="run-AG3-300"
            ),
        )
        == []
    )
