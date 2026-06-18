"""Productive composition + real source-port wiring for the RefreshWorker (AG3-082).

These tests exercise the REAL composition (not a spy injection), closing the
"built but not wired" gap (review FIX 1) and the "consume the real port" gap
(review FIX 2):

- FIX 1: ``build_kpi_analytics`` wires a REAL ``RefreshWorker`` (real
  ``StateBackendAnalyticsSource`` + real ``FactStore``) into ``KpiAnalytics``, so
  ``refresh_analytics`` reaches the real worker instead of returning the
  not-configured SKIPPED branch.
- FIX 2: ``StateBackendAnalyticsSource.purge_run_read_models`` consumes the REAL
  ``ProjectionAccessor.purge_run(project_key, story_id, run_id)`` — the single
  AG3-081/FK-69 reset surface (run-scoped, FK-69 §69.10.1) — and the worker's
  ``purge_story_analytics`` threads ``run_id`` through it.
- FIX 4: the real worker path computes the hint story's ``dirty_pipeline_weeks``
  entry from ``week_start(closed_at)`` of the just-closed story (read from its
  ``story_metrics``), NOT ``week_start(now)``.

Only the canonical state backend is used (SQLite test-parallel path) — no mock at
the worker boundary. The story/corpus read-models and the run-scoped purge run on
SQLite; the project-global event stream is Postgres-canonical, so the event-driven
delta path is asserted as a clean no-op on the empty SQLite event table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.bootstrap.composition_root import build_kpi_analytics
from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.kpi_analytics.aggregation import (
    EXPECTED_SCHEMA_VERSION,
    AffectedPeriods,
    RefreshWorker,
)
from agentkit.kpi_analytics.fact_store import FactStore, FactStory, PeriodFilter, SyncState
from agentkit.kpi_analytics.views import RefreshStatus
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.state_backend.store.analytics_source import StateBackendAnalyticsSource
from agentkit.state_backend.store.fact_repository import StateBackendFactRepository
from agentkit.state_backend.store.guard_counter_repository import (
    StateBackendGuardCounterRepository,
)
from agentkit.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PROJECT = "tenant-w"
_NOW = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
_WIDE = PeriodFilter(
    start=datetime(2020, 1, 1, tzinfo=UTC), end=datetime(2030, 1, 1, tzinfo=UTC)
)


@pytest.fixture(autouse=True)
def _pin_sqlite(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _seed_schema_version(store: FactStore) -> None:
    store.upsert_sync_state(
        SyncState(
            project_key=_PROJECT,
            key="schema_version",
            value_int=EXPECTED_SCHEMA_VERSION,
            updated_at=_NOW,
        )
    )


def _seed_story_metrics(
    accessor: ProjectionAccessor, *, story_id: str, completed_at: str
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
            processing_time_min=12.0,
            qa_rounds=2,
            increments=3,
            final_status="DONE",
            completed_at=completed_at,
            files_changed=4,
            agentkit_version="3.20.0",
            agentkit_commit="cafef00d",
        ),
    )


# ---------------------------------------------------------------------------
# FIX 1 — build_kpi_analytics wires the REAL worker (no SKIPPED-not-configured)
# ---------------------------------------------------------------------------


def test_build_kpi_analytics_wires_real_refresh_worker(tmp_path: Path) -> None:
    analytics = build_kpi_analytics(tmp_path, project_key=_PROJECT)

    # The productive builder reaches a REAL RefreshWorker over the real source —
    # not None (which would make refresh_analytics return SKIPPED in production).
    worker = analytics._refresh_worker  # noqa: SLF001 - asserting the wired graph
    assert isinstance(worker, RefreshWorker)
    assert isinstance(worker._source, StateBackendAnalyticsSource)  # noqa: SLF001


def test_productive_refresh_analytics_reaches_worker_not_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The facade dispatches into the REAL worker (not the SKIPPED-not-configured).

    The old wiring left ``refresh_worker=None``, so ``refresh_analytics`` returned
    SKIPPED in production. Now the productive builder injects the real worker, so
    the facade dispatches into it. The worker reads the project-global execution-
    event stream through the real source.

    AG3-094 (jenkins-460 scope-correction): the SQLite global execution-event store
    is now a REAL read (it backs the SSE E2E and is asserted by the cross-backend
    parity contract test), resolving its root from ``AGENTKIT_STORE_DIR`` (the same
    isolated ``tmp_path`` the FactStore uses). With no seeded events the watermark is
    ``None``, so the worker recomputes nothing and returns a NON-SKIPPED result
    (``UP_TO_DATE``) — proof the worker WAS reached (the not-configured SKIPPED
    branch is gone). This replaces the pre-AG3-094 assertion that the SQLite event
    read was unsupported (``RuntimeError`` "requires postgres"), which AG3-094's real
    SQLite event store deliberately superseded.
    """
    monkeypatch.setenv("AGENTKIT_STORE_DIR", str(tmp_path))
    _seed_schema_version(FactStore(StateBackendFactRepository(tmp_path)))
    analytics = build_kpi_analytics(tmp_path, project_key=_PROJECT)

    result = analytics.refresh_analytics(_PROJECT, hint_story_id="AG3-700")

    assert result.status is not RefreshStatus.SKIPPED


def test_productive_refresh_analytics_no_longer_returns_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The not-configured SKIPPED branch is unreachable once the worker is wired."""
    monkeypatch.setenv("AGENTKIT_STORE_DIR", str(tmp_path))
    _seed_schema_version(FactStore(StateBackendFactRepository(tmp_path)))
    analytics = build_kpi_analytics(tmp_path, project_key=_PROJECT)

    # Both deps are configured, so the facade NEVER takes the SKIPPED branch — it
    # dispatches to the worker, which reads the (empty) SQLite event stream and
    # returns a non-SKIPPED result.
    result = analytics.refresh_analytics(_PROJECT)
    assert result.status is not RefreshStatus.SKIPPED


# ---------------------------------------------------------------------------
# FIX 2 — purge consumes the REAL run-scoped ProjectionAccessor.purge_run
# ---------------------------------------------------------------------------


def test_purge_consumes_real_purge_run_with_run_id(tmp_path: Path) -> None:
    accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
    store = FactStore(StateBackendFactRepository(tmp_path))
    source = StateBackendAnalyticsSource(accessor, project_key=_PROJECT)
    worker = RefreshWorker(store, source)

    # Seed a story_metrics read-model + a fact_story row + a guard-counter scratchpad
    # for the reset story, so the run-scoped purge_run has real rows to remove.
    _seed_story_metrics(accessor, story_id="AG3-701", completed_at=_NOW.isoformat())
    store.upsert_fact_story(
        FactStory(
            project_key=_PROJECT,
            story_id="AG3-701",
            story_type="implementation",
            story_size="M",
            opened_at=_NOW,
            qa_round_count=1,
            computed_at=_NOW,
        )
    )
    counters = StateBackendGuardCounterRepository(tmp_path)
    counters.upsert_invocation(
        project_key=_PROJECT,
        story_id="AG3-701",
        guard_key="orchestrator_guard",
        week_start="2026-06-08",
        blocked=True,
        updated_at=_NOW,
    )

    worker.purge_story_analytics(
        _PROJECT, "AG3-701", "run-AG3-701", AffectedPeriods()
    )

    # fact_story gone (FK-62 §62.2.8).
    assert store.list_fact_stories(_PROJECT) == []
    # The REAL run-scoped purge_run removed the run-bound FK-69 read model ...
    assert (
        accessor.read_projection(
            ProjectionKind.STORY_METRICS,
            ProjectionFilter(
                project_key=_PROJECT, story_id="AG3-701", run_id="run-AG3-701"
            ),
        )
        == []
    )
    # ... and drained the guard-counter scratchpad as part of the SAME purge_run
    # (AG3-081/FK-61 §61.4.3 Trigger 4) — not via a second worker-side delete.
    assert counters.read_counters_for_story(_PROJECT, "AG3-701") == []


# ---------------------------------------------------------------------------
# FIX 4 — the real worker path computes the hint pipeline week from closed_at
# ---------------------------------------------------------------------------


def test_real_source_resolves_closed_at_for_hint_pipeline_week(
    tmp_path: Path,
) -> None:
    """The real source resolves ``closed_at`` from the hint story's ``story_metrics``.

    Complements the worker-path FIX 4 test (in ``test_refresh_worker.py``) at the
    real-adapter boundary: ``StateBackendAnalyticsSource.get_story_closed_at`` reads
    the seeded ``story_metrics`` and returns the real closure instant, so the dirty
    pipeline week derives from ``week_start(closed_at)`` — NOT ``week_start(now)``.
    """
    accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
    source = StateBackendAnalyticsSource(accessor, project_key=_PROJECT)

    # now = 2026-06-11 (week 2026-06-08); the hint story closed 2026-05-28
    # (week 2026-05-25) — a different week.
    closed_at = datetime(2026, 5, 28, 14, 0, tzinfo=UTC)
    closed_week = "2026-05-25"
    now_week = "2026-06-08"
    _seed_story_metrics(
        accessor, story_id="AG3-702", completed_at=closed_at.isoformat()
    )

    resolved = source.get_story_closed_at(_PROJECT, "AG3-702")
    assert resolved == closed_at

    from agentkit.kpi_analytics.aggregation.dirty_sets import derive_dirty_sets

    dirty = derive_dirty_sets(
        _PROJECT,
        [],
        hint_story_id="AG3-702",
        hint_closed_at=resolved,
        now=_NOW,
    )
    # The hint pipeline week is the CLOSED week, not the now-week.
    assert (_PROJECT, closed_week) in dirty.dirty_pipeline_weeks
    assert (_PROJECT, now_week) not in dirty.dirty_pipeline_weeks
