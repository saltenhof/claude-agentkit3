"""Cross-backend parity contract for the GLOBAL execution-event store.

AG3-094 (E8): the global execution-event store is the exact store the
project-scoped SSE stream (``/v1/projects/{key}/events``) and the KPI analytics
source read from. It MUST behave identically on SQLite and Postgres, otherwise a
change validated against local SQLite can silently break the Postgres path on
Jenkins (the original drift Codex flagged):

* **Ordering / limit window** — :func:`load_execution_events_for_project_global`
  returns the *most-recent N* rows (when ``limit`` is set) in *ascending*
  (chronological) order; with no ``limit`` it returns ALL rows ascending. Both
  backends must produce the identical sequence for identical arguments.
* **Project scoping** — only rows for the requested ``project_key`` are returned.
* **Dup-key semantics** — appending a row whose ``(project_key, run_id,
  event_id)`` already exists raises on BOTH backends (no silent
  ``INSERT OR IGNORE`` divergence on SQLite vs the plain Postgres insert).

The single ``_assert_global_event_store_contract`` body runs against whichever
backend is configured. The SQLite case runs everywhere (incl. local dev and the
no-Docker path). The Postgres case binds the Docker-gated ``postgres_backend_env``
fixture, so it executes on Jenkins where Postgres is available and is skipped
(by the fixture's own gating) when no Postgres is reachable. Because both cases
assert the SAME contract, the two backends cannot drift without one of them
failing here.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import psycopg
import pytest

from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV, STORE_DIR_ENV
from agentkit.state_backend.store import (
    append_execution_event_global,
    load_execution_events_for_project_global,
    reset_backend_cache_for_tests,
)
from agentkit.telemetry.contract.records import ExecutionEventRecord

if TYPE_CHECKING:
    from pathlib import Path

pytest_plugins = ("tests.fixtures.postgres_backend",)

_BASE_TS = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)


def _event(
    *,
    project_key: str,
    run_id: str,
    event_id: str,
    minute_offset: int,
) -> ExecutionEventRecord:
    return ExecutionEventRecord(
        project_key=project_key,
        story_id="AG3-PARITY",
        run_id=run_id,
        event_id=event_id,
        event_type="telemetry_event",
        occurred_at=_BASE_TS + timedelta(minutes=minute_offset),
        source_component="parity-test",
        severity="info",
        payload={"offset": minute_offset},
    )


def _assert_global_event_store_contract(
    *,
    integrity_error: type[Exception],
) -> None:
    """Run the backend-agnostic global execution-event store contract.

    Args:
        integrity_error: The duplicate-PK error class the active backend raises
            (``sqlite3.IntegrityError`` / ``psycopg.errors.UniqueViolation``).
    """
    project = "parity-proj"
    other_project = "other-proj"

    # Append five events for ``project`` in non-monotonic insert order so a naive
    # "insertion order" implementation cannot accidentally pass. occurred_at
    # offsets 0..4 with distinct event_ids.
    append_execution_event_global(
        _event(project_key=project, run_id="r1", event_id="e2", minute_offset=2),
    )
    append_execution_event_global(
        _event(project_key=project, run_id="r1", event_id="e0", minute_offset=0),
    )
    append_execution_event_global(
        _event(project_key=project, run_id="r1", event_id="e4", minute_offset=4),
    )
    append_execution_event_global(
        _event(project_key=project, run_id="r1", event_id="e1", minute_offset=1),
    )
    append_execution_event_global(
        _event(project_key=project, run_id="r1", event_id="e3", minute_offset=3),
    )
    # A row for a different project — must never leak into ``project`` reads.
    append_execution_event_global(
        _event(project_key=other_project, run_id="r9", event_id="x0", minute_offset=9),
    )

    # No limit -> ALL project rows, ascending (chronological) order.
    all_events = load_execution_events_for_project_global(project)
    assert [e.event_id for e in all_events] == ["e0", "e1", "e2", "e3", "e4"]
    # Project scoping: the other project's row is absent.
    assert all(e.project_key == project for e in all_events)

    # limit=3 -> most-recent THREE rows, still ascending (chronological).
    windowed = load_execution_events_for_project_global(project, limit=3)
    assert [e.event_id for e in windowed] == ["e2", "e3", "e4"]

    # limit larger than the row count -> all rows ascending.
    assert [e.event_id for e in load_execution_events_for_project_global(project, limit=99)] == [
        "e0",
        "e1",
        "e2",
        "e3",
        "e4",
    ]

    # Non-positive limit -> empty (fail-safe, identical on both backends).
    assert load_execution_events_for_project_global(project, limit=0) == []

    # Dup-key: re-appending the same (project_key, run_id, event_id) raises on
    # BOTH backends (no silent INSERT OR IGNORE divergence).
    with pytest.raises(integrity_error):
        append_execution_event_global(
            _event(project_key=project, run_id="r1", event_id="e0", minute_offset=0),
        )


@pytest.mark.contract
def test_global_event_store_contract_on_sqlite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """SQLite global execution-event store honours the parity contract."""
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    # E9: the SQLite global store resolves its root from AGENTKIT_STORE_DIR
    # (fail-closed), NOT Path.cwd().
    monkeypatch.setenv(STORE_DIR_ENV, str(tmp_path))
    reset_backend_cache_for_tests()
    try:
        _assert_global_event_store_contract(integrity_error=sqlite3.IntegrityError)
    finally:
        reset_backend_cache_for_tests()


@pytest.mark.contract
def test_global_event_store_contract_on_postgres(
    postgres_backend_env: object,
) -> None:
    """Postgres global execution-event store honours the SAME parity contract.

    Runs against the Docker-gated worker-scoped test schema; skipped by the
    fixture when no Postgres is reachable. Asserting the identical contract here
    is what prevents silent SQLite/Postgres drift in the SSE store.
    """
    del postgres_backend_env
    _assert_global_event_store_contract(
        integrity_error=psycopg.errors.UniqueViolation,
    )
