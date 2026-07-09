"""AG3-127 AC2: StateBackendProjectTelemetryEventSource over a REAL SQLite round-trip.

Persists project-scoped execution events via the canonical global write owner
(``append_execution_event_global``) into a real SQLite store, then reads them back
through the productive ``ProjectTelemetryEventSource`` adapter — the strongest
"really persisted" evidence for the telemetry read edge (not a fake). Adds the
``runtime_checkable`` conformance check additionally, not as a replacement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend.config import (
    ALLOW_SQLITE_ENV,
    STATE_BACKEND_ENV,
    STORE_DIR_ENV,
)
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.telemetry_read_repository import (
    StateBackendProjectTelemetryEventSource,
)
from agentkit.backend.state_backend.telemetry_event_store import append_execution_event_global
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.repository import ProjectTelemetryEventSource

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PROJECT = "tenant-a"
_OTHER = "tenant-b"
_BASE_TS = datetime(2026, 6, 16, 10, 0, tzinfo=UTC)


@pytest.fixture
def store_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    monkeypatch.setenv(STORE_DIR_ENV, str(tmp_path))
    monkeypatch.chdir(tmp_path)
    reset_backend_cache_for_tests()
    yield tmp_path
    reset_backend_cache_for_tests()


def _event(*, project_key: str, event_id: str, minute_offset: int) -> ExecutionEventRecord:
    return ExecutionEventRecord(
        project_key=project_key,
        story_id="AG3-127",
        run_id="run-127",
        event_id=event_id,
        event_type="telemetry_event",
        occurred_at=_BASE_TS + timedelta(minutes=minute_offset),
        source_component="pipeline-engine",
        severity="info",
        payload={"offset": minute_offset},
    )


def _seed(store_dir: Path) -> None:
    del store_dir  # global write owner resolves the active backend itself
    append_execution_event_global(_event(project_key=_PROJECT, event_id="e0", minute_offset=0))
    append_execution_event_global(_event(project_key=_PROJECT, event_id="e1", minute_offset=1))
    append_execution_event_global(_event(project_key=_PROJECT, event_id="e2", minute_offset=2))
    # A different project's event must never leak into the project-scoped read.
    append_execution_event_global(_event(project_key=_OTHER, event_id="x0", minute_offset=9))


def test_adapter_reads_persisted_project_events_on_sqlite(store_dir: Path) -> None:
    _seed(store_dir)
    adapter = StateBackendProjectTelemetryEventSource()

    # Structural runtime_checkable conformance (additionally, not as replacement).
    assert isinstance(adapter, ProjectTelemetryEventSource)

    events = adapter.events_for_project(_PROJECT)
    assert [e.event_id for e in events] == ["e0", "e1", "e2"]
    assert all(e.project_key == _PROJECT for e in events)
    assert events[0].payload == {"offset": 0}

    # limit selects the most-recent window (ascending order preserved).
    windowed = adapter.events_for_project(_PROJECT, limit=2)
    assert [e.event_id for e in windowed] == ["e1", "e2"]


def test_adapter_returns_empty_list_for_absent_project(store_dir: Path) -> None:
    # AC5 fail-closed (legit absence, not a masked backend failure): a fresh
    # store yields an empty list, never an error and never leaked cross-project data.
    _seed(store_dir)
    adapter = StateBackendProjectTelemetryEventSource()
    assert adapter.events_for_project("does-not-exist") == []
