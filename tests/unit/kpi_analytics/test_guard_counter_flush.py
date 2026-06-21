"""Guard-counter flush triggers + reset purge (FK-61 §61.4.3, AG3-081 AC5/AC6).

The four FK-61 §61.4.3 flush triggers each drain the ``guard_invocation_counters``
scratchpad deterministically (read + delete the matching rows, returning them for
the AG3-082 ``fact_guard_period`` re-aggregation): (1) Closure, (2) Week-Rollover,
(3) Housekeeping, (4) full Story-Reset. Each trigger is exercised here over the
real state-backend counter repository.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.kpi_analytics.fact_store.guard_counter import (
    GuardCounterService,
    week_start_for,
)
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.guard_counter_repository import (
    StateBackendGuardCounterRepository,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "tenant-a"
_STORY = "AG3-300"
_OTHER_STORY = "AG3-301"
_GUARD = "orchestrator_guard"


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _service(project_root: Path) -> GuardCounterService:
    return GuardCounterService(StateBackendGuardCounterRepository(project_root))


def _rows(project_root: Path, story_id: str = _STORY) -> int:
    return len(
        StateBackendGuardCounterRepository(project_root).read_counters_for_story(
            _PROJECT, story_id
        )
    )


# ---------------------------------------------------------------------------
# week_start_for convention
# ---------------------------------------------------------------------------


def test_week_start_is_iso_monday() -> None:
    # 2026-06-11 is a Thursday; its ISO week starts Monday 2026-06-08.
    assert week_start_for(datetime(2026, 6, 11, 9, 0, tzinfo=UTC)) == "2026-06-08"
    assert week_start_for(datetime(2026, 6, 8, 0, 0, tzinfo=UTC)) == "2026-06-08"


# ---------------------------------------------------------------------------
# Trigger 1 — Closure
# ---------------------------------------------------------------------------


def test_closure_flush_drains_story_counters(tmp_path: Path) -> None:
    service = _service(tmp_path)
    now = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    service.record_invocation(
        project_key=_PROJECT, story_id=_STORY, guard_key=_GUARD, blocked=True, now=now
    )
    service.record_invocation(
        project_key=_PROJECT, story_id=_STORY, guard_key=_GUARD, blocked=False, now=now
    )
    assert _rows(tmp_path) == 1

    drained = service.flush_on_closure(_PROJECT, _STORY)

    assert len(drained) == 1
    assert drained[0].invocations == 2
    assert drained[0].blocks == 1
    # Deterministic drain: no counter row survives the flush.
    assert _rows(tmp_path) == 0


# ---------------------------------------------------------------------------
# Trigger 2 — Week-Rollover
# ---------------------------------------------------------------------------


def test_week_rollover_flush_drains_older_weeks_only(tmp_path: Path) -> None:
    service = _service(tmp_path)
    last_week = datetime(2026, 6, 4, 9, 0, tzinfo=UTC)  # week of 2026-06-01
    this_week = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)  # week of 2026-06-08
    service.record_invocation(
        project_key=_PROJECT,
        story_id=_STORY,
        guard_key=_GUARD,
        blocked=False,
        now=last_week,
    )
    service.record_invocation(
        project_key=_PROJECT,
        story_id=_STORY,
        guard_key=_GUARD,
        blocked=False,
        now=this_week,
    )
    assert _rows(tmp_path) == 2  # two distinct weekly buckets

    drained = service.flush_week_rollover(_PROJECT, _STORY, now=this_week)

    # Only the older week is drained; the current week stays live.
    assert len(drained) == 1
    assert drained[0].week_start == "2026-06-01"
    remaining = StateBackendGuardCounterRepository(tmp_path).read_counters_for_story(
        _PROJECT, _STORY
    )
    assert [r.week_start for r in remaining] == ["2026-06-08"]


# ---------------------------------------------------------------------------
# Trigger 3 — Housekeeping (>24h without update)
# ---------------------------------------------------------------------------


def test_housekeeping_flush_drains_stale_counters(tmp_path: Path) -> None:
    service = _service(tmp_path)
    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    stale = now - timedelta(hours=30)
    fresh = now - timedelta(hours=1)
    service.record_invocation(
        project_key=_PROJECT,
        story_id=_STORY,
        guard_key=_GUARD,
        blocked=False,
        now=stale,
    )
    service.record_invocation(
        project_key=_PROJECT,
        story_id=_OTHER_STORY,
        guard_key=_GUARD,
        blocked=False,
        now=fresh,
    )

    drained = service.flush_housekeeping(now=now)

    # Only the >24h-stale row is drained; the fresh one stays.
    assert len(drained) == 1
    assert drained[0].story_id == _STORY
    assert _rows(tmp_path, _STORY) == 0
    assert _rows(tmp_path, _OTHER_STORY) == 1


# ---------------------------------------------------------------------------
# Trigger 4 — full Story-Reset
# ---------------------------------------------------------------------------


def test_story_reset_flush_purges_all_counters(tmp_path: Path) -> None:
    service = _service(tmp_path)
    now = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    for guard in (_GUARD, "self_protection"):
        service.record_invocation(
            project_key=_PROJECT,
            story_id=_STORY,
            guard_key=guard,
            blocked=False,
            now=now,
        )
    service.record_invocation(
        project_key=_PROJECT,
        story_id=_OTHER_STORY,
        guard_key=_GUARD,
        blocked=False,
        now=now,
    )
    assert _rows(tmp_path) == 2

    drained = service.flush_on_story_reset(_PROJECT, _STORY)

    assert len(drained) == 2
    # No counter row of the reset story survives; another story is untouched.
    assert _rows(tmp_path, _STORY) == 0
    assert _rows(tmp_path, _OTHER_STORY) == 1
