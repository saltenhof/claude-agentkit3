"""StateBackendArtifactRepository — SQLite/Postgres implementation of ArtifactRepository.

Concrete implementation of the ``ArtifactRepository`` protocol from
``agentkit.artifacts.repository`` for the state_backend BC.

Design decisions:
- Backend switch via env var ``AGENTKIT_STATE_BACKEND`` (sqlite/postgres),
  analogous to ``story_repository.py``.
- The record key is a deterministic compound key of the identity fields:
  ``<story_id>|<run_id>|<stage>|<attempt>|<artifact_class>|<producer_name>``
  -> same fields = same key -> exists/read idempotent.
- A UNIQUE constraint on the primary key blocks a double insert.
  ``write_envelope`` uses INSERT OR IGNORE (SQLite) / ON CONFLICT DO NOTHING
  (Postgres) -- idempotent for the same identity fields.
- Fail-closed: no silent None return on a backend error; exceptions
  propagate directly.

Sources:
- AG3-023 §2.1.2 — ArtifactRepository contract
- AG3-023 §2.1.4 — schema columns and constraints
- AG3-023 §2.1.4.2 — idempotency
- FK-18 §18.9a — side-by-side DB per SCHEMA_VERSION
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
    """SQLite/Postgres implementation of the ArtifactRepository protocol.

    The backend is selected via the ``AGENTKIT_STATE_BACKEND`` env var
    (``sqlite`` or ``postgres``).

    The reference is deterministic: same identity fields ->
    same ``record_key`` -> exists/read idempotent. A double insert
    is prevented by a UNIQUE constraint on the primary key
    (INSERT OR IGNORE for SQLite, ON CONFLICT DO NOTHING for Postgres).

    Args:
        store_dir: Base directory for the state backend (contains
            ``.agentkit/``). Only relevant for SQLite. Default: cwd.

    Architecture Conformance:
        This module is the only ``state_backend``-internal consumer
        of the ArtifactEnvelope/Reference models. It imports them
        directly from ``agentkit.artifacts`` (not via the facade).
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    # ------------------------------------------------------------------
    # write_envelope
    # ------------------------------------------------------------------

    def write_envelope(self, envelope: ArtifactEnvelope) -> ArtifactReference:
        """Persist a valid ArtifactEnvelope (UPSERT).

        Fail-closed against divergent truth: on the same primary key
        (story_id, run_id, stage, attempt, artifact_class, producer_name)
        the call UPDATEs all non-key columns to the current
        envelope values. This keeps ``artifact_envelopes`` the single
        source of truth so it cannot diverge from the
        projection (AG3-023 §AK4, re-review finding 2).

        Args:
            envelope: Fully validated ArtifactEnvelope.

        Returns:
            Deterministic ArtifactReference.

        Raises:
            Exception: Backend error (I/O, constraint violation).
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
            story_id: Story display id.
            run_id: Run correlation id (None matches across all runs).
            artifact_class: Producer-class filter.
            stage: Stage filter (e.g. ``qa-policy-decision``).

        Returns:
            Latest ``ArtifactEnvelope`` or ``None``.
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
    # find_prompt_audit_output_hashes (FK-44 §44.6 / FK-31 §31.7.4)
    # ------------------------------------------------------------------

    def find_prompt_audit_output_hashes(
        self,
        *,
        story_id: str,
        run_id: str,
    ) -> frozenset[str]:
        """Return all prompt-audit ``output_sha256`` values for a (story, run).

        The prompt-runtime materialization (``PromptRuntime.materialize_prompt``,
        FK-44 §44.6) persists one ``ArtifactClass.PROMPT_AUDIT`` envelope per
        spawned prompt, carrying ``output_sha256`` -- the digest of the EXACT
        materialized prompt bytes the agent receives, provably rendered from a
        manifest-pinned bundle template (the template digests are folded into the
        bundle manifest hash at install). This set is the FK-31 §31.7.4 Stage-3
        baseline: it is install-pinned and NOT spawn-controlled, so a worker can
        neither author it nor point at a self-made file to satisfy it.

        Unlike :meth:`find_latest_envelope` (single highest-attempt match per
        stage), Stage 3 must accept ANY prompt the pipeline legitimately
        materialized for this run (worker / qa / remediation / exploration), so
        the full per-run scope is returned, not just the latest.

        Args:
            story_id: Story-Display-ID.
            run_id: Run-Korrelations-ID (the prompt-audit run scope).

        Returns:
            The frozenset of all ``output_sha256`` digests for the scope (empty
            when none materialized -- a story_execution spawn then has no pinned
            baseline and is fail-closed blocked at Stage 3).
        """
        if _is_postgres():
            rows = self._pg_prompt_audit_payloads(story_id, run_id)
        else:
            rows = self._sqlite_prompt_audit_payloads(story_id, run_id)
        hashes: set[str] = set()
        for raw_payload in rows:
            if raw_payload is None:
                continue
            payload = (
                raw_payload
                if isinstance(raw_payload, dict)
                else json.loads(str(raw_payload))
            )
            digest = payload.get("output_sha256")
            if isinstance(digest, str) and digest:
                hashes.add(digest)
        return frozenset(hashes)

    def _sqlite_prompt_audit_payloads(
        self, story_id: str, run_id: str
    ) -> list[object]:
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                """
                SELECT payload_json FROM artifact_envelopes
                WHERE story_id = ? AND run_id = ? AND artifact_class = ?
                """,
                (story_id, run_id, ArtifactClass.PROMPT_AUDIT.value),
            )
            return [dict(row).get("payload_json") for row in cursor.fetchall()]

    def _pg_prompt_audit_payloads(
        self, story_id: str, run_id: str
    ) -> list[object]:
        with _postgres_connect() as conn:
            _ensure_artifact_table_postgres(conn)
            cursor = conn.execute(
                """
                SELECT payload_json FROM artifact_envelopes
                WHERE story_id = %s AND run_id = %s AND artifact_class = %s
                """,
                (story_id, run_id, ArtifactClass.PROMPT_AUDIT.value),
            )
            return [dict(row).get("payload_json") for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # read_envelope
    # ------------------------------------------------------------------

    def read_envelope(self, reference: ArtifactReference) -> ArtifactEnvelope | None:
        """Load an ArtifactEnvelope by its reference.

        Args:
            reference: Deterministic record key from ``write_envelope``.

        Returns:
            ArtifactEnvelope if present, else None.
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
        """Check the existence of an envelope by its reference.

        Args:
            reference: Deterministic record key.

        Returns:
            True if present, False otherwise.
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
