"""StateBackendGuardCounterRepository — guard-invocation counter scratchpad (AG3-081).

Productive SQLite/Postgres implementation of the consumer-owned
``GuardCounterRepository`` Protocol
(``agentkit.backend.kpi_analytics.fact_store.repository``), backing the FK-61 §61.4.3
hot-path scratchpad ``guard_invocation_counters``. Mirrors
``StateBackendFactRepository``:

- Postgres is the canonical truth; SQLite is the test-parallel path
  (``AGENTKIT_ALLOW_SQLITE=1``). The DDL lives in the canonical schema
  (``postgres_schema.sql`` / ``migration/versions/v_3_4_analytics.sql``); this
  adapter carries no DDL truth.
- The hot-path UPSERT is the FK-61 §61.4.3 statement verbatim
  (``ON CONFLICT ... DO UPDATE SET invocations = invocations + 1,
  blocks = blocks + EXCLUDED.blocks``).
- Fail-closed: a read against a missing table propagates the backend error — never
  a silent empty result.

Architecture Conformance (AC8): the KPI fact-store knows only the
``GuardCounterRepository`` Protocol (defined in ``kpi_analytics.fact_store``); this
adapter is wired in the composition root / at the runner edge.
``kpi_analytics.fact_store`` never imports this module.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from agentkit.backend.kpi_analytics.fact_store.models import GuardInvocationCounter

if TYPE_CHECKING:
    from collections.abc import Iterator


def _is_postgres() -> bool:
    from agentkit.backend.state_backend.config import (
        StateBackendKind,
        load_state_backend_config,
    )

    return load_state_backend_config().backend is StateBackendKind.POSTGRES


def _assert_sqlite_allowed() -> None:
    from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed

    if not _sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for this path. "
            f"Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )


def _sqlite_db_path(store_dir: Path) -> Path:
    from agentkit.backend.state_backend.config import versioned_sqlite_db_file
    from agentkit.backend.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    from agentkit.backend.state_backend import sqlite_store

    _assert_sqlite_allowed()
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        # Setup runs inside try so a bootstrap failure closes the conn (no leak).
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        sqlite_store._ensure_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    from agentkit.backend.state_backend import postgres_store
    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    with postgres_store.borrow_repository_connection() as conn:
        ensure_versioned_schema(conn)
        postgres_store._ensure_schema_once(postgres_store._CompatConnection(conn))
        conn.commit()
        yield conn


def _ts(value: datetime, *, is_postgres: bool) -> Any:
    """Bind ``updated_at`` (TIMESTAMPTZ on Postgres, ISO-8601 TEXT on SQLite)."""
    return value if is_postgres else value.isoformat()


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _row_to_counter(row: dict[str, Any]) -> GuardInvocationCounter:
    return GuardInvocationCounter(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        guard_key=str(row["guard_key"]),
        week_start=str(row["week_start"]),
        invocations=int(row["invocations"]),
        blocks=int(row["blocks"]),
        updated_at=_dt(row["updated_at"]),
    )


@dataclass(frozen=True)
class GuardCounterRecordOutcome:
    """Outcome of an atomic idempotent guard-counter record (AG3-129, FK-91 Rule 5).

    Attributes:
        status: ``"recorded"`` (new ``op_id``: counter incremented AND the
            consolidated ``control_plane_operations`` record written in ONE
            transaction), ``"replayed"`` (``op_id`` already seen
            with the SAME body hash; the counter is NOT re-incremented), or
            ``"mismatch"`` (``op_id`` reused with a DIFFERENT body hash — the caller
            raises the canonical ``idempotency_mismatch`` conflict).
        cached_result: The stored result payload on a ``"replayed"`` outcome.
        drained: Number of older-week buckets drained by a ``"recorded"`` write
            (Week-Rollover, FK-61 §61.4.3 Trigger 2); ``0`` for replay/mismatch.
    """

    status: Literal["recorded", "replayed", "mismatch"]
    cached_result: dict[str, Any] | None = None
    drained: int = 0


class StateBackendGuardCounterRepository:
    """SQLite/Postgres implementation of ``GuardCounterRepository`` (AG3-081).

    Backend selected via ``AGENTKIT_STATE_BACKEND``; Postgres is canonical, SQLite
    is the test-parallel path (``AGENTKIT_ALLOW_SQLITE=1``).

    Args:
        store_dir: Base directory for the SQLite store (Postgres ignores it).
            Default: ``Path.cwd()``.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    def upsert_invocation(
        self,
        *,
        project_key: str,
        story_id: str,
        guard_key: str,
        week_start: str,
        blocked: bool,
        updated_at: datetime,
    ) -> None:
        """UPSERT one guard invocation (FK-61 §61.4.3 statement verbatim)."""
        is_pg = _is_postgres()
        if is_pg:
            with _postgres_connect() as conn:
                self._upsert_counter_row(
                    conn,
                    is_pg=True,
                    project_key=project_key,
                    story_id=story_id,
                    guard_key=guard_key,
                    week_start=week_start,
                    blocked=blocked,
                    updated_at=updated_at,
                )
            return
        with _sqlite_connect(self._store_dir) as conn:
            self._upsert_counter_row(
                conn,
                is_pg=False,
                project_key=project_key,
                story_id=story_id,
                guard_key=guard_key,
                week_start=week_start,
                blocked=blocked,
                updated_at=updated_at,
            )

    def record_invocation_idempotent(
        self,
        *,
        op_id: str,
        body_hash: str,
        result_payload: dict[str, Any],
        project_key: str,
        story_id: str,
        guard_key: str,
        week_start: str,
        blocked: bool,
        updated_at: datetime,
        created_at: datetime,
    ) -> GuardCounterRecordOutcome:
        """Record one invocation EXACTLY ONCE per ``op_id`` (FK-91 §91.1a Rule 5).

        AG3-129 (concurrency-safe) + AG3-140 (unified idempotency contract): the
        idempotency record is the ONE consolidated ``control_plane_operations`` row
        whose ``op_id`` PRIMARY KEY is the real unique gate. Inside ONE transaction
        that terminal row is INSERTed FIRST (plain INSERT — NO
        ``ON CONFLICT DO NOTHING``); only if the claim succeeds are the older-week
        buckets drained (Week-Rollover, FK-61 §61.4.3 Trigger 2) and the counter
        incremented — so all counter side effects commit/roll back atomically with
        the record. A unique-constraint violation (a concurrent OR sequential
        duplicate ``op_id``) rolls the whole transaction back — the loser does NOT
        count and does NOT drain — and is then resolved by a re-SELECT: same body
        hash → ``"replayed"`` (return the stored result); different body hash →
        ``"mismatch"`` (the caller raises the canonical conflict). ``result_payload``
        is the placeholder response stored on the record at claim time; the accurate
        drained count is returned in :attr:`GuardCounterRecordOutcome.drained` and
        written back onto the record so a later replay returns it unchanged.

        Returns:
            A :class:`GuardCounterRecordOutcome`.
        """
        try:
            if _is_postgres():
                with _postgres_connect() as conn:
                    drained = self._claim_and_record(
                        conn,
                        is_pg=True,
                        op_id=op_id,
                        body_hash=body_hash,
                        result_payload=result_payload,
                        project_key=project_key,
                        story_id=story_id,
                        guard_key=guard_key,
                        week_start=week_start,
                        blocked=blocked,
                        updated_at=updated_at,
                        created_at=created_at,
                    )
            else:
                with _sqlite_connect(self._store_dir) as conn:
                    drained = self._claim_and_record(
                        conn,
                        is_pg=False,
                        op_id=op_id,
                        body_hash=body_hash,
                        result_payload=result_payload,
                        project_key=project_key,
                        story_id=story_id,
                        guard_key=guard_key,
                        week_start=week_start,
                        blocked=blocked,
                        updated_at=updated_at,
                        created_at=created_at,
                    )
        except Exception:  # noqa: BLE001 -- unique-gate loser OR a genuine fault
            # The transaction rolled back (no count, no drain). If the op_id now
            # resolves, this was the unique-gate duplicate path -> replay/mismatch;
            # otherwise it was a genuine fault -> propagate (fail-closed).
            existing = self._read_idempotency_key(op_id)
            if existing is None:
                raise
            existing_hash, cached = existing
            if existing_hash != body_hash:
                return GuardCounterRecordOutcome(status="mismatch")
            return GuardCounterRecordOutcome(status="replayed", cached_result=cached)
        return GuardCounterRecordOutcome(status="recorded", drained=drained)

    def _claim_and_record(
        self,
        conn: Any,
        *,
        is_pg: bool,
        op_id: str,
        body_hash: str,
        result_payload: dict[str, Any],
        project_key: str,
        story_id: str,
        guard_key: str,
        week_start: str,
        blocked: bool,
        updated_at: datetime,
        created_at: datetime,
    ) -> int:
        """Claim ``op_id`` (unique gate) then drain+count in ONE transaction.

        Raises the backend unique-constraint error when ``op_id`` already exists
        (the caller resolves it to replay/mismatch); on that raise the whole
        transaction — including any drain/count — rolls back.
        """
        # 1. Claim the op_id FIRST (unique gate) by inserting the terminal
        #    control_plane_operations record. A duplicate raises here, before any
        #    counter side effect, and aborts the transaction.
        self._insert_idempotency_row(
            conn,
            is_pg=is_pg,
            op_id=op_id,
            project_key=project_key,
            story_id=story_id,
            body_hash=body_hash,
            result_payload=result_payload,
            created_at=created_at,
        )
        # 2. New accepted record ONLY: drain older-week buckets (Trigger 2) and
        #    increment the current week — atomic with the claim above.
        drained = self._drain_older_weeks(
            conn,
            is_pg=is_pg,
            project_key=project_key,
            story_id=story_id,
            week_start=week_start,
        )
        self._upsert_counter_row(
            conn,
            is_pg=is_pg,
            project_key=project_key,
            story_id=story_id,
            guard_key=guard_key,
            week_start=week_start,
            blocked=blocked,
            updated_at=updated_at,
        )
        # 3. Persist the accurate drained count onto the stored result so a later
        #    replay returns the SAME response (idempotency contract).
        self._update_idempotency_result(
            conn,
            is_pg=is_pg,
            op_id=op_id,
            result_payload={**result_payload, "drained": drained},
        )
        return drained

    def _read_idempotency_key(
        self, op_id: str
    ) -> tuple[str, dict[str, Any]] | None:
        """Return ``(body_hash, result_payload)`` for ``op_id``, or ``None``.

        Reads the ONE consolidated ``control_plane_operations`` record (AG3-140):
        ``request_body_hash`` is the replay-vs-mismatch discriminator and
        ``response_json`` (a JSON string on BOTH backends) is the stored result.
        """
        is_pg = _is_postgres()
        placeholder = "%s" if is_pg else "?"
        query = (
            "SELECT request_body_hash, response_json "
            f"FROM control_plane_operations WHERE op_id = {placeholder}"
        )
        if is_pg:
            with _postgres_connect() as conn:
                row = conn.execute(query, (op_id,)).fetchone()
        else:
            with _sqlite_connect(self._store_dir) as conn:
                row = conn.execute(query, (op_id,)).fetchone()
        if row is None:
            return None
        payload = row["response_json"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return str(row["request_body_hash"]), dict(payload)

    @staticmethod
    def _drain_older_weeks(
        conn: Any,
        *,
        is_pg: bool,
        project_key: str,
        story_id: str,
        week_start: str,
    ) -> int:
        """Delete counter rows of weeks strictly BEFORE ``week_start``; return count."""
        placeholder = "%s" if is_pg else "?"
        cursor = conn.execute(
            "DELETE FROM guard_invocation_counters "
            f"WHERE project_key = {placeholder} AND story_id = {placeholder} "
            f"AND week_start < {placeholder}",
            (project_key, story_id, week_start),
        )
        return int(cursor.rowcount)

    @staticmethod
    def _update_idempotency_result(
        conn: Any,
        *,
        is_pg: bool,
        op_id: str,
        result_payload: dict[str, Any],
    ) -> None:
        # Overwrite the one-record ``response_json`` with the accurate drained count
        # so a later replay returns it unchanged. ``response_json`` is TEXT (a JSON
        # string) on BOTH backends -- pass the json string, NOT ``::jsonb``.
        if is_pg:
            conn.execute(
                "UPDATE control_plane_operations SET response_json = %s "
                "WHERE op_id = %s",
                (json.dumps(result_payload), op_id),
            )
            return
        conn.execute(
            "UPDATE control_plane_operations SET response_json = ? WHERE op_id = ?",
            (json.dumps(result_payload), op_id),
        )

    @staticmethod
    def _upsert_counter_row(
        conn: Any,
        *,
        is_pg: bool,
        project_key: str,
        story_id: str,
        guard_key: str,
        week_start: str,
        blocked: bool,
        updated_at: datetime,
    ) -> None:
        params = {
            "project_key": project_key,
            "story_id": story_id,
            "guard_key": guard_key,
            "week_start": week_start,
            "blocks_inc": 1 if blocked else 0,
            "updated_at": _ts(updated_at, is_postgres=is_pg),
        }
        columns = (
            "project_key, story_id, guard_key, week_start, invocations, blocks, "
            "updated_at"
        )
        update_clause = (
            "invocations = guard_invocation_counters.invocations + 1, "
            "blocks = guard_invocation_counters.blocks + EXCLUDED.blocks, "
            "updated_at = EXCLUDED.updated_at"
        )
        conflict = "project_key, story_id, guard_key, week_start"
        if is_pg:
            conn.execute(
                f"INSERT INTO guard_invocation_counters ({columns}) "
                "VALUES (%(project_key)s, %(story_id)s, %(guard_key)s, "
                "%(week_start)s, 1, %(blocks_inc)s, %(updated_at)s) "
                f"ON CONFLICT ({conflict}) DO UPDATE SET {update_clause}",
                params,
            )
            return
        conn.execute(
            f"INSERT INTO guard_invocation_counters ({columns}) "
            "VALUES (:project_key, :story_id, :guard_key, :week_start, 1, "
            ":blocks_inc, :updated_at) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {update_clause}",
            params,
        )

    @staticmethod
    def _insert_idempotency_row(
        conn: Any,
        *,
        is_pg: bool,
        op_id: str,
        project_key: str,
        story_id: str,
        body_hash: str,
        result_payload: dict[str, Any],
        created_at: datetime,
    ) -> None:
        # PLAIN INSERT (no ON CONFLICT / OR IGNORE): the op_id PRIMARY KEY of the ONE
        # consolidated control_plane_operations record is the concurrency gate — a
        # duplicate MUST raise so the loser rolls back and is resolved to
        # replay/mismatch (AG3-129 round-5 FUND 1; AG3-140 one-record consolidation).
        # The guard-counter op is instantaneous, so a TERMINAL 'committed' row is
        # written in one shot (no claim→finalize window; claimed_by/claimed_at and
        # the AG3-137 fencing columns stay NULL). response_json is TEXT (a JSON
        # string) on BOTH backends — pass the json string, NOT ``::jsonb``.
        created = created_at.isoformat()
        columns = (
            "op_id, project_key, story_id, operation_kind, status, "
            "response_json, request_body_hash, created_at, updated_at"
        )
        params = (
            op_id,
            project_key,
            story_id,
            "guard_counter_record",
            "committed",
            json.dumps(result_payload),
            body_hash,
            created,
            created,
        )
        if is_pg:
            conn.execute(
                f"INSERT INTO control_plane_operations ({columns}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                params,
            )
            return
        conn.execute(
            f"INSERT INTO control_plane_operations ({columns}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            params,
        )

    def read_counters_for_story(
        self, project_key: str, story_id: str
    ) -> list[GuardInvocationCounter]:
        """Return all counter rows for ``(project_key, story_id)``."""
        return self._select(
            "SELECT * FROM guard_invocation_counters WHERE project_key = ? "
            "AND story_id = ? ORDER BY guard_key, week_start",
            (project_key, story_id),
        )

    def read_counters_for_story_before_week(
        self, project_key: str, story_id: str, week_start: str
    ) -> list[GuardInvocationCounter]:
        """Return counter rows of older weeks (``week_start < week_start``)."""
        return self._select(
            "SELECT * FROM guard_invocation_counters WHERE project_key = ? "
            "AND story_id = ? AND week_start < ? ORDER BY guard_key, week_start",
            (project_key, story_id, week_start),
        )

    def read_counters_stale(self, cutoff: datetime) -> list[GuardInvocationCounter]:
        """Return counter rows older than ``cutoff`` (by ``updated_at``)."""
        return self._select(
            "SELECT * FROM guard_invocation_counters WHERE updated_at < ? "
            "ORDER BY project_key, story_id, guard_key, week_start",
            (_ts(cutoff, is_postgres=_is_postgres()),),
        )

    def delete_counters_for_story(self, project_key: str, story_id: str) -> int:
        """Delete every counter row for ``(project_key, story_id)``."""
        return self._execute(
            "DELETE FROM guard_invocation_counters WHERE project_key = ? "
            "AND story_id = ?",
            (project_key, story_id),
        )

    def delete_counters_for_story_before_week(
        self, project_key: str, story_id: str, week_start: str
    ) -> int:
        """Delete older-week counter rows (``week_start < week_start``)."""
        return self._execute(
            "DELETE FROM guard_invocation_counters WHERE project_key = ? "
            "AND story_id = ? AND week_start < ?",
            (project_key, story_id, week_start),
        )

    def delete_counters_stale(self, cutoff: datetime) -> int:
        """Delete counter rows older than ``cutoff`` (by ``updated_at``)."""
        return self._execute(
            "DELETE FROM guard_invocation_counters WHERE updated_at < ?",
            (_ts(cutoff, is_postgres=_is_postgres()),),
        )

    # ------------------------------------------------------------------
    # internal engine
    # ------------------------------------------------------------------

    def _select(
        self, query: str, params: tuple[Any, ...]
    ) -> list[GuardInvocationCounter]:
        if _is_postgres():
            with _postgres_connect() as conn:
                rows = conn.execute(query.replace("?", "%s"), params).fetchall()
            return [_row_to_counter(dict(r)) for r in rows]
        with _sqlite_connect(self._store_dir) as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_counter(dict(r)) for r in rows]

    def _execute(self, statement: str, params: tuple[Any, ...]) -> int:
        if _is_postgres():
            with _postgres_connect() as conn:
                cursor = conn.execute(statement.replace("?", "%s"), params)
                return int(cursor.rowcount)
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(statement, params)
            return int(cursor.rowcount)


__all__ = ["GuardCounterRecordOutcome", "StateBackendGuardCounterRepository"]
