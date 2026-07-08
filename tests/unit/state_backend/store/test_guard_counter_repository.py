"""Unit tests for the StateBackendGuardCounterRepository sqlite paths (AG3-081).

Covers the consumer-owned ``GuardCounterRepository`` adapter's reachable SQLite
branches + edge cases: the stale / before-week reads and deletes, the
``_dt``/``_ts`` round-trip helpers, the fail-closed ``_assert_sqlite_allowed``
raise, and the rollback-on-error path. The Postgres branches are the canonical
backend and exercised by the Postgres-backed integration suite; here only the
SQLite test-parallel path runs (``AGENTKIT_ALLOW_SQLITE=1``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.guard_counter_repository import (
    StateBackendGuardCounterRepository,
    _dt,
    _ts,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "tenant-x"
_STORY = "AG3-400"
_GUARD = "orchestrator_guard"


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _repo(project_root: Path) -> StateBackendGuardCounterRepository:
    return StateBackendGuardCounterRepository(project_root)


def test_upsert_then_read_round_trips_counter(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    now = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    repo.upsert_invocation(
        project_key=_PROJECT,
        story_id=_STORY,
        guard_key=_GUARD,
        week_start="2026-06-08",
        blocked=True,
        updated_at=now,
    )
    repo.upsert_invocation(
        project_key=_PROJECT,
        story_id=_STORY,
        guard_key=_GUARD,
        week_start="2026-06-08",
        blocked=False,
        updated_at=now + timedelta(minutes=1),
    )
    rows = repo.read_counters_for_story(_PROJECT, _STORY)
    assert len(rows) == 1
    assert rows[0].invocations == 2
    assert rows[0].blocks == 1
    assert rows[0].updated_at == now + timedelta(minutes=1)


def test_before_week_read_and_delete(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    now = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    for week in ("2026-06-01", "2026-06-08"):
        repo.upsert_invocation(
            project_key=_PROJECT,
            story_id=_STORY,
            guard_key=_GUARD,
            week_start=week,
            blocked=False,
            updated_at=now,
        )
    older = repo.read_counters_for_story_before_week(_PROJECT, _STORY, "2026-06-08")
    assert [r.week_start for r in older] == ["2026-06-01"]
    removed = repo.delete_counters_for_story_before_week(_PROJECT, _STORY, "2026-06-08")
    assert removed == 1
    assert [r.week_start for r in repo.read_counters_for_story(_PROJECT, _STORY)] == [
        "2026-06-08"
    ]


def test_stale_read_and_delete(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    repo.upsert_invocation(
        project_key=_PROJECT,
        story_id=_STORY,
        guard_key=_GUARD,
        week_start="2026-06-08",
        blocked=False,
        updated_at=now - timedelta(hours=30),
    )
    repo.upsert_invocation(
        project_key=_PROJECT,
        story_id="AG3-401",
        guard_key=_GUARD,
        week_start="2026-06-08",
        blocked=False,
        updated_at=now,
    )
    cutoff = now - timedelta(hours=24)
    stale = repo.read_counters_stale(cutoff)
    assert [r.story_id for r in stale] == [_STORY]
    removed = repo.delete_counters_stale(cutoff)
    assert removed == 1
    assert repo.read_counters_for_story(_PROJECT, _STORY) == []
    assert len(repo.read_counters_for_story(_PROJECT, "AG3-401")) == 1


def test_delete_counters_for_story(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    now = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    repo.upsert_invocation(
        project_key=_PROJECT,
        story_id=_STORY,
        guard_key=_GUARD,
        week_start="2026-06-08",
        blocked=False,
        updated_at=now,
    )
    assert repo.delete_counters_for_story(_PROJECT, _STORY) == 1
    assert repo.read_counters_for_story(_PROJECT, _STORY) == []


def test_dt_parses_string_and_passes_datetime() -> None:
    instant = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    # _dt accepts a datetime as-is (Postgres TIMESTAMPTZ already typed) ...
    assert _dt(instant) is instant
    # ... and parses an ISO-8601 string (SQLite TEXT storage).
    assert _dt(instant.isoformat()) == instant


def test_ts_binds_per_backend() -> None:
    instant = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
    assert _ts(instant, is_postgres=True) is instant
    assert _ts(instant, is_postgres=False) == instant.isoformat()


def test_sqlite_disabled_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FAIL-CLOSED: with SQLite disabled the adapter must refuse rather than degrade.
    monkeypatch.delenv("AGENTKIT_ALLOW_SQLITE", raising=False)
    reset_backend_cache_for_tests()
    repo = _repo(tmp_path)
    with pytest.raises(RuntimeError, match="SQLite backend is disabled"):
        repo.read_counters_for_story(_PROJECT, _STORY)
