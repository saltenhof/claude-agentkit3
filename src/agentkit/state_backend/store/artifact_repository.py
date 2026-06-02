"""StateBackendArtifactRepository — SQLite/Postgres-Implementierung von ArtifactRepository.

Konkrete Implementierung des ``ArtifactRepository``-Protocols aus
``agentkit.artifacts.repository`` fuer den state_backend-BC.

Design-Entscheidungen:
- Backend-Switch per Env-Var ``AGENTKIT_STATE_BACKEND`` (sqlite/postgres),
  analog zu ``story_repository.py``.
- Record-Key ist ein deterministischer Compound-Key aus den Identitaetsfeldern:
  ``<story_id>|<run_id>|<stage>|<attempt>|<artifact_class>|<producer_name>``
  -> gleiche Felder = gleicher Key -> exists/read idempotent.
- UNIQUE-Constraint auf dem Primaerschluessel blockt Doppelt-Insert.
  ``write_envelope`` nutzt INSERT OR IGNORE (SQLite) / ON CONFLICT DO NOTHING
  (Postgres) -- idempotent bei gleichen Identitaetsfeldern.
- Fail-closed: kein silent None-Return bei Backend-Fehler; Exceptions
  propagieren direkt.

Quellen:
- AG3-023 §2.1.2 — ArtifactRepository-Vertrag
- AG3-023 §2.1.4 — Schema-Spalten und Constraints
- AG3-023 §2.1.4.2 — Idempotenz
- FK-18 §18.9a — Side-by-Side-DB pro SCHEMA_VERSION
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.artifacts.envelope import ArtifactEnvelope
from agentkit.artifacts.producer import Producer, ProducerId, ProducerType
from agentkit.artifacts.reference import ArtifactReference
from agentkit.core_types import ArtifactClass, EnvelopeStatus

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Backend detection (same pattern as story_repository.py)
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    """Return True when AGENTKIT_STATE_BACKEND=postgres."""
    return os.environ.get("AGENTKIT_STATE_BACKEND", "sqlite").lower() == "postgres"


def _assert_sqlite_allowed() -> None:
    """Raise RuntimeError if SQLite backend is not explicitly enabled.

    Enforces the AGENTKIT_ALLOW_SQLITE=1 gating pattern (Fix E8, AG3-031 Pass-6).
    """
    from agentkit.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed

    if not _sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for this path. "
            f"Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )


def _postgres_database_url() -> str:
    url = os.environ.get("AGENTKIT_STATE_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "AGENTKIT_STATE_DATABASE_URL must be set when "
            "AGENTKIT_STATE_BACKEND=postgres"
        )
    return url


# ---------------------------------------------------------------------------
# Key computation — deterministic, same fields -> same key
# ---------------------------------------------------------------------------


def _record_key(
    story_id: str,
    run_id: str,
    stage: str,
    attempt: int,
    artifact_class: ArtifactClass,
    producer_name: str,
) -> str:
    """Compute the canonical record_key for an ArtifactReference."""
    return f"{story_id}|{run_id}|{stage}|{attempt}|{artifact_class}|{producer_name}"


def _reference_from_envelope(envelope: ArtifactEnvelope) -> ArtifactReference:
    key = _record_key(
        story_id=envelope.story_id,
        run_id=envelope.run_id,
        stage=envelope.stage,
        attempt=envelope.attempt,
        artifact_class=envelope.artifact_class,
        producer_name=envelope.producer.name,
    )
    return ArtifactReference(
        artifact_class=envelope.artifact_class,
        story_id=envelope.story_id,
        run_id=envelope.run_id,
        record_key=key,
    )


def _parse_record_key(record_key: str) -> tuple[str, str, str, int, str, str]:
    """Parse record_key back into (story_id, run_id, stage, attempt, artifact_class, producer_name)."""
    parts = record_key.split("|", 5)
    if len(parts) != 6:
        raise ValueError(f"Ungueltige record_key-Struktur: {record_key!r}")
    story_id, run_id, stage, attempt_str, artifact_class_str, producer_name = parts
    return story_id, run_id, stage, int(attempt_str), artifact_class_str, producer_name


# ---------------------------------------------------------------------------
# Row <-> Envelope conversion (SQLite — TEXT timestamps, TEXT JSON)
# ---------------------------------------------------------------------------


def _envelope_to_sqlite_row(envelope: ArtifactEnvelope) -> dict[str, Any]:
    """Serialize ArtifactEnvelope to a SQLite row dict."""
    return {
        "story_id": envelope.story_id,
        "run_id": envelope.run_id,
        "stage": envelope.stage,
        "attempt": envelope.attempt,
        "schema_version": envelope.schema_version,
        "producer_type": envelope.producer.type.value,
        "producer_id": str(envelope.producer.id),
        "producer_name": envelope.producer.name,
        "producer_version": envelope.producer.version,
        "started_at": envelope.started_at.isoformat(),
        "finished_at": envelope.finished_at.isoformat(),
        "status": envelope.status.value,
        "artifact_class": envelope.artifact_class.value,
        "payload_json": json.dumps(envelope.payload, sort_keys=True)
        if envelope.payload is not None
        else None,
    }


def _sqlite_row_to_envelope(row: dict[str, Any]) -> ArtifactEnvelope:
    """Deserialize a SQLite row dict to ArtifactEnvelope."""
    payload: dict[str, Any] | None = None
    raw_payload = row.get("payload_json")
    if raw_payload is not None:
        payload = json.loads(str(raw_payload))

    started_at = datetime.fromisoformat(str(row["started_at"]))
    finished_at = datetime.fromisoformat(str(row["finished_at"]))
    # Ensure UTC tz-awareness preserved through TEXT roundtrip
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=UTC)

    return ArtifactEnvelope(
        schema_version="3.0",
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        stage=str(row["stage"]),
        attempt=int(row["attempt"]),
        producer=Producer(
            type=ProducerType(str(row["producer_type"])),
            name=str(row["producer_name"]),
            id=ProducerId(str(row["producer_id"])),
            version=str(row["producer_version"])
            if row.get("producer_version") is not None
            else None,
        ),
        started_at=started_at,
        finished_at=finished_at,
        status=EnvelopeStatus(str(row["status"])),
        artifact_class=ArtifactClass(str(row["artifact_class"])),
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Row <-> Envelope conversion (Postgres — TIMESTAMPTZ, JSON column)
# ---------------------------------------------------------------------------


def _envelope_to_pg_row(envelope: ArtifactEnvelope) -> dict[str, Any]:
    """Serialize ArtifactEnvelope to a Postgres row dict."""
    return {
        "story_id": envelope.story_id,
        "run_id": envelope.run_id,
        "stage": envelope.stage,
        "attempt": envelope.attempt,
        "schema_version": envelope.schema_version,
        "producer_type": envelope.producer.type.value,
        "producer_id": str(envelope.producer.id),
        "producer_name": envelope.producer.name,
        "producer_version": envelope.producer.version,
        "started_at": envelope.started_at.isoformat(),
        "finished_at": envelope.finished_at.isoformat(),
        "status": envelope.status.value,
        "artifact_class": envelope.artifact_class.value,
        "payload_json": json.dumps(envelope.payload, sort_keys=True)
        if envelope.payload is not None
        else None,
    }


def _pg_row_to_envelope(row: dict[str, Any]) -> ArtifactEnvelope:
    """Deserialize a Postgres row dict to ArtifactEnvelope."""
    payload: dict[str, Any] | None = None
    raw_payload = row.get("payload_json")
    if raw_payload is not None:
        payload = raw_payload if isinstance(raw_payload, dict) else json.loads(str(raw_payload))

    started_at = row["started_at"]
    finished_at = row["finished_at"]
    if isinstance(started_at, str):
        started_at = datetime.fromisoformat(started_at)
    if isinstance(finished_at, str):
        finished_at = datetime.fromisoformat(finished_at)
    # Postgres TIMESTAMPTZ returns tz-aware values in the connection's session
    # timezone (e.g. Europe/Berlin on a localized server), but FK-71 §71.2
    # requires UTC offset 0. Normalize regardless of the incoming tz: convert
    # aware values to UTC, and treat naive values as already-UTC.
    started_at = (
        started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at.astimezone(UTC)
    )
    finished_at = (
        finished_at.replace(tzinfo=UTC) if finished_at.tzinfo is None else finished_at.astimezone(UTC)
    )

    return ArtifactEnvelope(
        schema_version="3.0",
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        stage=str(row["stage"]),
        attempt=int(row["attempt"]),
        producer=Producer(
            type=ProducerType(str(row["producer_type"])),
            name=str(row["producer_name"]),
            id=ProducerId(str(row["producer_id"])),
            version=str(row["producer_version"])
            if row.get("producer_version") is not None
            else None,
        ),
        started_at=started_at,
        finished_at=finished_at,
        status=EnvelopeStatus(str(row["status"])),
        artifact_class=ArtifactClass(str(row["artifact_class"])),
        payload=payload,
    )


# ---------------------------------------------------------------------------
# SQLite connection helper
# ---------------------------------------------------------------------------


def _sqlite_db_path(store_dir: Path) -> Path:
    """Return the versioned SQLite database path."""
    from agentkit.state_backend.config import versioned_sqlite_db_file
    from agentkit.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _assert_sqlite_allowed()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_artifact_table_sqlite(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_artifact_table_sqlite(conn: sqlite3.Connection) -> None:
    """Create the artifact_envelopes table and index idempotently.

    Uses CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS per
    FK-18 §18.9a idempotency requirement (AG3-023 §2.1.4.2).

    Separate table from the legacy ``artifact_records`` table used by
    ``sqlite_store.persist_layer_artifact_rows`` (old QA-persistence path).
    The new ``artifact_envelopes`` table owns the typed Envelope-schema
    (AG3-023 §2.1.4); the legacy table is untouched.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS artifact_envelopes (
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            schema_version TEXT NOT NULL,
            producer_type TEXT NOT NULL CHECK (producer_type IN ('WORKER', 'LLM_REVIEWER', 'DETERMINISTIC')),
            producer_id TEXT NOT NULL,
            producer_name TEXT NOT NULL,
            producer_version TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            status TEXT NOT NULL,
            artifact_class TEXT NOT NULL CHECK (artifact_class IN (
                'worker', 'qa', 'pipeline', 'telemetry', 'governance',
                'entwurf', 'handover', 'adversarial_test_sandbox',
                'prompt_audit'
            )),
            payload_json TEXT,
            PRIMARY KEY (story_id, run_id, stage, attempt, artifact_class, producer_name)
        );

        CREATE INDEX IF NOT EXISTS artifact_envelopes_story_run_stage_attempt_idx
            ON artifact_envelopes (story_id, run_id, stage, attempt);
        """
    )


def _ensure_artifact_table_postgres(conn: Any) -> None:
    """Create the artifact_envelopes table and index idempotently on Postgres.

    Uses CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS per
    FK-18 §18.9a idempotency requirement (AG3-023 §2.1.4.2).
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS artifact_envelopes (
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            schema_version VARCHAR NOT NULL,
            producer_type VARCHAR NOT NULL CHECK (producer_type IN ('WORKER', 'LLM_REVIEWER', 'DETERMINISTIC')),
            producer_id VARCHAR NOT NULL,
            producer_name VARCHAR NOT NULL,
            producer_version VARCHAR NULL,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ NOT NULL,
            status VARCHAR NOT NULL,
            artifact_class VARCHAR NOT NULL CHECK (artifact_class IN (
                'worker', 'qa', 'pipeline', 'telemetry', 'governance',
                'entwurf', 'handover', 'adversarial_test_sandbox',
                'prompt_audit'
            )),
            payload_json JSON,
            PRIMARY KEY (story_id, run_id, stage, attempt, artifact_class, producer_name)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS artifact_envelopes_story_run_stage_attempt_idx
            ON artifact_envelopes (story_id, run_id, stage, attempt)
        """
    )


# ---------------------------------------------------------------------------
# Postgres connection helper
# ---------------------------------------------------------------------------


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    """Open a psycopg connection with dict_row factory and versioned schema."""
    import psycopg
    from psycopg.rows import dict_row

    from agentkit.state_backend.schema_bootstrap import ensure_versioned_schema

    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        ensure_versioned_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# StateBackendArtifactRepository
# ---------------------------------------------------------------------------


class StateBackendArtifactRepository:
    """SQLite/Postgres-Implementierung des ArtifactRepository-Protocols.

    Backend wird per ``AGENTKIT_STATE_BACKEND``-Env-Var gewaehlt
    (``sqlite`` oder ``postgres``).

    Die Reference ist deterministisch: gleiche Identitaetsfelder ->
    gleicher ``record_key`` -> exists/read idempotent. Doppelt-Insert
    wird per UNIQUE-Constraint auf dem Primaerschluessel verhindert
    (INSERT OR IGNORE fuer SQLite, ON CONFLICT DO NOTHING fuer Postgres).

    Args:
        store_dir: Basisverzeichnis fuer das State-Backend (enthaelt
            ``.agentkit/``). Nur fuer SQLite relevant. Default: cwd.

    Architecture Conformance:
        Dieses Modul ist der einzige ``state_backend``-interne Konsument
        der ArtifactEnvelope/Reference-Modelle. Es importiert diese
        direkt aus ``agentkit.artifacts`` (nicht ueber die Fassade).
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    # ------------------------------------------------------------------
    # write_envelope
    # ------------------------------------------------------------------

    def write_envelope(self, envelope: ArtifactEnvelope) -> ArtifactReference:
        """Persistiert einen validen ArtifactEnvelope (UPSERT).

        Fail-closed gegen divergente Wahrheit: bei gleichem Primary-Key
        (story_id, run_id, stage, attempt, artifact_class, producer_name)
        UPDATEt der Aufruf alle nicht-Key-Spalten auf die aktuellen
        Envelope-Werte. So bleibt ``artifact_envelopes`` die einzige
        Source-of-Truth und kann nicht auseinanderlaufen mit der
        Projektion (AG3-023 §AK4, Re-Review-Befund 2).

        Args:
            envelope: Vollstaendig validierter ArtifactEnvelope.

        Returns:
            Deterministische ArtifactReference.

        Raises:
            Exception: Backend-Fehler (I/O, Constraint-Verletzung).
        """
        reference = _reference_from_envelope(envelope)
        if _is_postgres():
            self._pg_write(envelope)
        else:
            self._sqlite_write(envelope)
        return reference

    def _sqlite_write(self, envelope: ArtifactEnvelope) -> None:
        row = _envelope_to_sqlite_row(envelope)
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute(
                """
                INSERT INTO artifact_envelopes (
                    story_id, run_id, stage, attempt,
                    schema_version, producer_type, producer_id,
                    producer_name, producer_version,
                    started_at, finished_at, status, artifact_class,
                    payload_json
                ) VALUES (
                    :story_id, :run_id, :stage, :attempt,
                    :schema_version, :producer_type, :producer_id,
                    :producer_name, :producer_version,
                    :started_at, :finished_at, :status, :artifact_class,
                    :payload_json
                )
                ON CONFLICT(story_id, run_id, stage, attempt, artifact_class, producer_name)
                DO UPDATE SET
                    schema_version=excluded.schema_version,
                    producer_type=excluded.producer_type,
                    producer_id=excluded.producer_id,
                    producer_version=excluded.producer_version,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    status=excluded.status,
                    payload_json=excluded.payload_json
                """,
                row,
            )

    def _pg_write(self, envelope: ArtifactEnvelope) -> None:
        row = _envelope_to_pg_row(envelope)
        with _postgres_connect() as conn:
            _ensure_artifact_table_postgres(conn)
            conn.execute(
                """
                INSERT INTO artifact_envelopes (
                    story_id, run_id, stage, attempt,
                    schema_version, producer_type, producer_id,
                    producer_name, producer_version,
                    started_at, finished_at, status, artifact_class,
                    payload_json
                ) VALUES (
                    %(story_id)s, %(run_id)s, %(stage)s, %(attempt)s,
                    %(schema_version)s, %(producer_type)s, %(producer_id)s,
                    %(producer_name)s, %(producer_version)s,
                    %(started_at)s, %(finished_at)s, %(status)s,
                    %(artifact_class)s,
                    %(payload_json)s::json
                )
                ON CONFLICT (story_id, run_id, stage, attempt, artifact_class, producer_name)
                DO UPDATE SET
                    schema_version=excluded.schema_version,
                    producer_type=excluded.producer_type,
                    producer_id=excluded.producer_id,
                    producer_version=excluded.producer_version,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    status=excluded.status,
                    payload_json=excluded.payload_json
                """,
                row,
            )

    # ------------------------------------------------------------------
    # find_latest_envelope (AG3-023 §AK4 — read via Manager)
    # ------------------------------------------------------------------

    def find_latest_envelope(
        self,
        *,
        story_id: str,
        run_id: str | None,
        artifact_class: ArtifactClass,
        stage: str,
    ) -> ArtifactEnvelope | None:
        """Return the highest-attempt envelope matching the scope (or None).

        Args:
            story_id: Story-Display-ID.
            run_id: Run-Korrelations-ID (None matched ueber alle runs).
            artifact_class: Erzeugerklasse-Filter.
            stage: Stage-Filter (z.B. ``qa-policy-decision``).

        Returns:
            Latest ``ArtifactEnvelope`` oder ``None``.
        """
        if _is_postgres():
            return self._pg_find_latest(story_id, run_id, artifact_class, stage)
        return self._sqlite_find_latest(story_id, run_id, artifact_class, stage)

    def _sqlite_find_latest(
        self,
        story_id: str,
        run_id: str | None,
        artifact_class: ArtifactClass,
        stage: str,
    ) -> ArtifactEnvelope | None:
        with _sqlite_connect(self._store_dir) as conn:
            if run_id is None:
                cursor = conn.execute(
                    """
                    SELECT * FROM artifact_envelopes
                    WHERE story_id = ? AND stage = ? AND artifact_class = ?
                    ORDER BY attempt DESC
                    LIMIT 1
                    """,
                    (story_id, stage, artifact_class.value),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM artifact_envelopes
                    WHERE story_id = ? AND run_id = ? AND stage = ?
                      AND artifact_class = ?
                    ORDER BY attempt DESC
                    LIMIT 1
                    """,
                    (story_id, run_id, stage, artifact_class.value),
                )
            row = cursor.fetchone()
            if row is None:
                return None
            return _sqlite_row_to_envelope(dict(row))

    def _pg_find_latest(
        self,
        story_id: str,
        run_id: str | None,
        artifact_class: ArtifactClass,
        stage: str,
    ) -> ArtifactEnvelope | None:
        with _postgres_connect() as conn:
            _ensure_artifact_table_postgres(conn)
            if run_id is None:
                cursor = conn.execute(
                    """
                    SELECT * FROM artifact_envelopes
                    WHERE story_id = %s AND stage = %s AND artifact_class = %s
                    ORDER BY attempt DESC
                    LIMIT 1
                    """,
                    (story_id, stage, artifact_class.value),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM artifact_envelopes
                    WHERE story_id = %s AND run_id = %s AND stage = %s
                      AND artifact_class = %s
                    ORDER BY attempt DESC
                    LIMIT 1
                    """,
                    (story_id, run_id, stage, artifact_class.value),
                )
            row = cursor.fetchone()
            if row is None:
                return None
            return _pg_row_to_envelope(dict(row))

    # ------------------------------------------------------------------
    # read_envelope
    # ------------------------------------------------------------------

    def read_envelope(self, reference: ArtifactReference) -> ArtifactEnvelope | None:
        """Laedt einen ArtifactEnvelope anhand seiner Reference.

        Args:
            reference: Deterministischer Record-Key aus ``write_envelope``.

        Returns:
            ArtifactEnvelope wenn vorhanden, sonst None.
        """
        try:
            story_id, run_id, stage, attempt, artifact_class_str, producer_name = (
                _parse_record_key(reference.record_key)
            )
        except ValueError:
            return None

        if _is_postgres():
            return self._pg_read(story_id, run_id, stage, attempt, artifact_class_str, producer_name)
        return self._sqlite_read(story_id, run_id, stage, attempt, artifact_class_str, producer_name)

    def _sqlite_read(
        self,
        story_id: str,
        run_id: str,
        stage: str,
        attempt: int,
        artifact_class_str: str,
        producer_name: str,
    ) -> ArtifactEnvelope | None:
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                """
                SELECT * FROM artifact_envelopes
                WHERE story_id = ? AND run_id = ? AND stage = ?
                  AND attempt = ? AND artifact_class = ? AND producer_name = ?
                """,
                (story_id, run_id, stage, attempt, artifact_class_str, producer_name),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _sqlite_row_to_envelope(dict(row))

    def _pg_read(
        self,
        story_id: str,
        run_id: str,
        stage: str,
        attempt: int,
        artifact_class_str: str,
        producer_name: str,
    ) -> ArtifactEnvelope | None:
        with _postgres_connect() as conn:
            _ensure_artifact_table_postgres(conn)
            cursor = conn.execute(
                """
                SELECT * FROM artifact_envelopes
                WHERE story_id = %s AND run_id = %s AND stage = %s
                  AND attempt = %s AND artifact_class = %s AND producer_name = %s
                """,
                (story_id, run_id, stage, attempt, artifact_class_str, producer_name),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _pg_row_to_envelope(dict(row))

    # ------------------------------------------------------------------
    # exists_envelope
    # ------------------------------------------------------------------

    def exists_envelope(self, reference: ArtifactReference) -> bool:
        """Prueft Existenz eines Envelopes anhand seiner Reference.

        Args:
            reference: Deterministischer Record-Key.

        Returns:
            True wenn vorhanden, False sonst.
        """
        try:
            story_id, run_id, stage, attempt, artifact_class_str, producer_name = (
                _parse_record_key(reference.record_key)
            )
        except ValueError:
            return False

        if _is_postgres():
            return self._pg_exists(story_id, run_id, stage, attempt, artifact_class_str, producer_name)
        return self._sqlite_exists(story_id, run_id, stage, attempt, artifact_class_str, producer_name)

    def _sqlite_exists(
        self,
        story_id: str,
        run_id: str,
        stage: str,
        attempt: int,
        artifact_class_str: str,
        producer_name: str,
    ) -> bool:
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM artifact_envelopes
                WHERE story_id = ? AND run_id = ? AND stage = ?
                  AND attempt = ? AND artifact_class = ? AND producer_name = ?
                """,
                (story_id, run_id, stage, attempt, artifact_class_str, producer_name),
            )
            row = cursor.fetchone()
            return bool(row[0]) if row else False

    def _pg_exists(
        self,
        story_id: str,
        run_id: str,
        stage: str,
        attempt: int,
        artifact_class_str: str,
        producer_name: str,
    ) -> bool:
        with _postgres_connect() as conn:
            _ensure_artifact_table_postgres(conn)
            cursor = conn.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM artifact_envelopes
                    WHERE story_id = %s AND run_id = %s AND stage = %s
                      AND attempt = %s AND artifact_class = %s AND producer_name = %s
                )
                """,
                (story_id, run_id, stage, attempt, artifact_class_str, producer_name),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            # psycopg dict_row returns {'exists': True/False}
            val = next(iter(row.values())) if isinstance(row, dict) else row[0]
            return bool(val)


__all__ = ["StateBackendArtifactRepository"]
