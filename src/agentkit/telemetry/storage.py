"""SQLite storage backend for telemetry events.

WAL mode for concurrent access.  Non-blocking -- errors logged, never
raised.  Telemetry must never block the pipeline (ARCH-40).
Side-effects are confined to this storage boundary (ARCH-31).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.telemetry.events import Event, EventType

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id TEXT NOT NULL,
    run_id TEXT,
    event_type TEXT NOT NULL,
    phase TEXT,
    payload TEXT,
    timestamp TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
)
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_events_story_type ON events (story_id, event_type)",
    "CREATE INDEX IF NOT EXISTS idx_events_run ON events (run_id)",
]


class SqliteEmitter:
    """SQLite-backed event emitter.

    Non-blocking: ``emit()`` catches all SQLite errors and logs them.
    Telemetry must never block the pipeline (ARCH-40).

    Args:
        db_path: Path to the SQLite database file.  Parent directories
            are created automatically.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't exist.

        Idempotent -- safe to call multiple times.
        """
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute(CREATE_TABLE)
                for idx_sql in CREATE_INDEXES:
                    conn.execute(idx_sql)
        except sqlite3.Error:
            logger.warning(
                "Failed to initialise telemetry schema at %s",
                self._db_path,
                exc_info=True,
            )

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with WAL mode and busy timeout.

        Returns:
            A configured SQLite connection.
        """
        conn = sqlite3.connect(str(self._db_path), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def emit(self, event: Event) -> None:
        """Write an event to SQLite.  Never raises (ARCH-19 / ARCH-40).

        Args:
            event: The immutable event to persist.
        """
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO events "
                    "(story_id, run_id, event_type, phase, payload, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        event.story_id,
                        event.run_id,
                        event.event_type.value,
                        event.phase,
                        json.dumps(event.payload, default=str),
                        event.timestamp.isoformat(),
                    ),
                )
        except sqlite3.Error:
            logger.warning(
                "Failed to emit event %s for %s",
                event.event_type,
                event.story_id,
                exc_info=True,
            )

    def query(
        self, story_id: str, event_type: EventType | None = None
    ) -> list[Event]:
        """Query events from SQLite.

        Args:
            story_id: The story to query events for.
            event_type: Optional filter for a specific event type.

        Returns:
            List of matching ``Event`` objects, ordered by id ascending.
        """
        try:
            with self._connect() as conn:
                if event_type is not None:
                    cursor = conn.execute(
                        "SELECT story_id, run_id, event_type, phase, payload, "
                        "timestamp FROM events "
                        "WHERE story_id = ? AND event_type = ? ORDER BY id",
                        (story_id, event_type.value),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT story_id, run_id, event_type, phase, payload, "
                        "timestamp FROM events "
                        "WHERE story_id = ? ORDER BY id",
                        (story_id,),
                    )
                return [self._row_to_event(row) for row in cursor.fetchall()]
        except sqlite3.Error:
            logger.warning(
                "Failed to query events for %s",
                story_id,
                exc_info=True,
            )
            return []

    @staticmethod
    def _row_to_event(
        row: tuple[str, str | None, str, str | None, str | None, str],
    ) -> Event:
        """Convert a database row to an ``Event`` instance.

        Args:
            row: Tuple of (story_id, run_id, event_type, phase, payload,
                timestamp).

        Returns:
            Reconstructed ``Event``.
        """
        story_id, run_id, event_type_str, phase, payload_str, ts_str = row
        payload: dict[str, object] = (
            json.loads(payload_str) if payload_str else {}
        )
        timestamp = datetime.fromisoformat(ts_str)
        # Ensure UTC timezone if the parsed timestamp is naive
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return Event(
            story_id=story_id,
            event_type=EventType(event_type_str),
            timestamp=timestamp,
            phase=phase,
            payload=payload,
            run_id=run_id,
        )
