"""Integration: AG3-147 push-freshness / push-backlog rows against REAL Postgres.

Exercises the Postgres-only read surface (AC5/AC13) that only a real Postgres
can prove: the upsert round-trip, the last-writer-wins per repo, and the
backlog projection persisted across a ``behind_remote`` report.

The ``postgres_isolated_schema`` fixture is auto-attached to every
``/integration/state_backend/`` item (``tests/integration/conftest.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane.push_sync import (
    PushFreshnessRecord,
    project_push_freshness,
)
from agentkit.backend.state_backend.story_closure_store import (
    list_push_freshness_records_global,
    load_push_freshness_record_global,
    upsert_push_freshness_record_global,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 7, 6, 10, 0, tzinfo=UTC)
_LATER = datetime(2026, 7, 6, 11, 0, tzinfo=UTC)
_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _record(
    *,
    repo_id: str,
    reported: str | None,
    pushed: str | None,
    at: datetime,
    backlog: bool,
    detail: str | None,
    sync_point_id: str | None = "phase_completion:op-1",
    command_id: str | None = None,
) -> PushFreshnessRecord:
    actual_command_id = (
        command_id
        if command_id is not None or sync_point_id is None
        else f"run-1::sync_push::{sync_point_id}::{repo_id}"
    )
    return PushFreshnessRecord(
        project_key="tenant-a",
        story_id="AG3-147",
        run_id="run-1",
        repo_id=repo_id,
        last_reported_head_sha=reported,
        last_pushed_head_sha=pushed,
        last_reported_at=at,
        last_sync_point_id=sync_point_id,
        last_command_id=actual_command_id,
        backlog=backlog,
        backlog_detail=detail,
    )


def test_upsert_and_load_round_trips_a_freshness_record() -> None:
    upsert_push_freshness_record_global(
        _record(
            repo_id="repo-a",
            reported=_SHA_A,
            pushed=_SHA_A,
            at=_NOW,
            backlog=False,
            detail=None,
        )
    )

    loaded = load_push_freshness_record_global("tenant-a", "AG3-147", "run-1", "repo-a")

    assert loaded is not None
    assert loaded.last_pushed_head_sha == _SHA_A
    assert loaded.backlog is False
    assert loaded.backlog_detail is None
    assert loaded.last_reported_at == _NOW


def test_upsert_is_last_writer_wins_per_repo() -> None:
    upsert_push_freshness_record_global(
        _record(
            repo_id="repo-b",
            reported=_SHA_A,
            pushed=_SHA_A,
            at=_NOW,
            backlog=False,
            detail=None,
        )
    )
    # A later behind_remote report raises a visible backlog while preserving the
    # prior pushed SHA (projected by the A-core), then persisted (AC4).
    previous = load_push_freshness_record_global("tenant-a", "AG3-147", "run-1", "repo-b")
    assert previous is not None
    projected = project_push_freshness(
        previous,
        project_key="tenant-a",
        story_id="AG3-147",
        run_id="run-1",
        repo_id="repo-b",
        reported_head_sha=_SHA_B,
        push_outcome="behind_remote",
        reported_at=_LATER,
        sync_point_id="phase_completion:op-2",
        command_id="run-1::sync_push::phase_completion:op-2::repo-b",
    )
    upsert_push_freshness_record_global(projected)

    reloaded = load_push_freshness_record_global("tenant-a", "AG3-147", "run-1", "repo-b")
    assert reloaded is not None
    assert reloaded.backlog is True
    assert reloaded.backlog_detail is not None
    assert reloaded.last_reported_head_sha == _SHA_B
    assert reloaded.last_sync_point_id == "phase_completion:op-2"
    assert reloaded.last_command_id == "run-1::sync_push::phase_completion:op-2::repo-b"
    # The last KNOWN pushed head is preserved across the backlog report.
    assert reloaded.last_pushed_head_sha == _SHA_A


def test_list_returns_one_row_per_repo_ordered() -> None:
    upsert_push_freshness_record_global(
        _record(
            repo_id="repo-z",
            reported=_SHA_A,
            pushed=_SHA_A,
            at=_NOW,
            backlog=False,
            detail=None,
        )
    )
    upsert_push_freshness_record_global(
        _record(
            repo_id="repo-a",
            reported=_SHA_B,
            pushed=None,
            at=_NOW,
            backlog=True,
            detail="behind remote",
        )
    )

    rows = list_push_freshness_records_global("tenant-a", "AG3-147", "run-1")

    repo_ids = [r.repo_id for r in rows]
    assert repo_ids == sorted(repo_ids)
    assert {"repo-a", "repo-z"}.issubset(set(repo_ids))
