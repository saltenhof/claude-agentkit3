"""Unit tests for agentkit.telemetry.storage (SqliteEmitter)."""

from __future__ import annotations

import os
import stat
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.telemetry.emitters import EventEmitter
from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.storage import SqliteEmitter


class TestSqliteEmitterCreation:
    """Tests for SqliteEmitter initialisation."""

    def test_creates_db_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        SqliteEmitter(db_path)
        assert db_path.exists()

    def test_schema_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        SqliteEmitter(db_path)
        SqliteEmitter(db_path)  # Second init must not raise
        assert db_path.exists()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sub" / "dir" / "telemetry.db"
        SqliteEmitter(db_path)
        assert db_path.exists()


class TestSqliteEmitterEmitQuery:
    """Tests for emit and query operations."""

    def test_emit_and_query_roundtrip(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        emitter = SqliteEmitter(db_path)
        ts = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)
        evt = Event(
            story_id="AG3-001",
            event_type=EventType.PHASE_STARTED,
            timestamp=ts,
            phase="setup",
            payload={"key": "value"},
            run_id="run-1",
        )
        emitter.emit(evt)
        results = emitter.query("AG3-001")
        assert len(results) == 1
        r = results[0]
        assert r.story_id == "AG3-001"
        assert r.event_type == EventType.PHASE_STARTED
        assert r.phase == "setup"
        assert r.payload == {"key": "value"}
        assert r.run_id == "run-1"

    def test_query_filters_by_event_type(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        emitter = SqliteEmitter(db_path)
        emitter.emit(Event(story_id="AG3-001", event_type=EventType.PHASE_STARTED))
        emitter.emit(Event(story_id="AG3-001", event_type=EventType.PHASE_COMPLETED))
        emitter.emit(Event(story_id="AG3-001", event_type=EventType.ERROR))
        results = emitter.query("AG3-001", event_type=EventType.PHASE_COMPLETED)
        assert len(results) == 1
        assert results[0].event_type == EventType.PHASE_COMPLETED

    def test_query_filters_by_story_id(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        emitter = SqliteEmitter(db_path)
        emitter.emit(Event(story_id="AG3-001", event_type=EventType.PHASE_STARTED))
        emitter.emit(Event(story_id="AG3-002", event_type=EventType.PHASE_STARTED))
        results = emitter.query("AG3-002")
        assert len(results) == 1
        assert results[0].story_id == "AG3-002"

    def test_query_other_story_returns_empty(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        emitter = SqliteEmitter(db_path)
        emitter.emit(Event(story_id="AG3-001", event_type=EventType.PHASE_STARTED))
        results = emitter.query("AG3-999")
        assert results == []

    def test_multiple_events_for_same_story(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        emitter = SqliteEmitter(db_path)
        event_types = (
            EventType.PHASE_STARTED,
            EventType.PHASE_COMPLETED,
            EventType.QA_DECISION,
        )
        for et in event_types:
            emitter.emit(Event(story_id="AG3-001", event_type=et))
        results = emitter.query("AG3-001")
        assert len(results) == 3

    def test_payload_roundtrip_complex(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        emitter = SqliteEmitter(db_path)
        payload: dict[str, object] = {
            "nested": {"a": 1},
            "list_val": [1, 2, 3],
            "flag": True,
        }
        emitter.emit(
            Event(
                story_id="AG3-001",
                event_type=EventType.WORKER_SPAWNED,
                payload=payload,
            )
        )
        results = emitter.query("AG3-001")
        assert results[0].payload == payload


class TestSqliteEmitterErrorHandling:
    """Tests for non-blocking error behaviour."""

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Windows does not support read-only directories reliably for SQLite",
    )
    def test_emit_on_db_error_does_not_raise(self, tmp_path: Path) -> None:
        # Create a read-only directory to force SQLite write failure
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        db_path = ro_dir / "telemetry.db"
        # Create the DB first, then make the directory read-only
        emitter = SqliteEmitter(db_path)
        os.chmod(str(ro_dir), stat.S_IRUSR | stat.S_IXUSR)
        try:
            # This should log a warning but NOT raise
            evt = Event(story_id="AG3-001", event_type=EventType.ERROR)
            emitter.emit(evt)  # Must not raise
        finally:
            os.chmod(str(ro_dir), stat.S_IRWXU)

    def test_emit_with_closed_connection_does_not_raise(self, tmp_path: Path) -> None:
        """Emit to a corrupt/inaccessible DB path does not raise."""
        # Point to a path where a directory exists with same name as the DB
        blocker = tmp_path / "telemetry.db"
        blocker.mkdir()  # Create a directory, not a file
        # SqliteEmitter will fail to connect but should not raise
        emitter = SqliteEmitter.__new__(SqliteEmitter)
        emitter._db_path = blocker
        evt = Event(story_id="AG3-001", event_type=EventType.ERROR)
        emitter.emit(evt)  # Must not raise


class TestSqliteEmitterProtocol:
    """Verify SqliteEmitter implements the EventEmitter protocol."""

    def test_implements_event_emitter_protocol(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        emitter = SqliteEmitter(db_path)
        assert isinstance(emitter, EventEmitter)
