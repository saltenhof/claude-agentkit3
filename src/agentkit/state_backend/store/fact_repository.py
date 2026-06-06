"""StateBackendFactRepository — analytics fact-table persistence (AG3-038).

Productive SQLite/Postgres implementation of the consumer-owned
``FactRepository`` Protocol (``agentkit.kpi_analytics.fact_store.repository``),
backing the FactStore (FK-62 §62.3). Mirrors ``project_registration_repository``:

- Postgres is the canonical truth (FK-60 §60.3.2); SQLite is the test-only
  parallel path (``AGENTKIT_ALLOW_SQLITE=1``). No co-equal dual-backend run.
- Analytics DDL has ONE authoritative path per backend: the typed Postgres truth
  is ``postgres_schema.sql``; the SQLite truth is the versioned migration
  ``migration/versions/v_3_4_analytics.sql`` applied by the ``MigrationRunner``
  (FK-62 §62.4) from ``sqlite_store._ensure_analytics_tables``. Both bootstraps
  also run the MigrationRunner so it records logical analytics version 3.4 in the
  idempotent ``schema_versions`` cursor — wired in production, not dead code.
  This adapter carries no DDL truth; it bootstraps the canonical schema and only
  reads/writes.
- ``upsert_*`` is INSERT-or-replace on the natural PK (idempotent re-write, no
  duplicate) so the (follow-up) RefreshWorker can re-run a slice safely.
- Fail-closed (story §7): a read against a missing fact table propagates the
  underlying database error — NEVER a silent empty result.

Architecture Conformance (AC8): the FactStore knows only the ``FactRepository``
Protocol (defined in ``kpi_analytics.fact_store``); this adapter is wired in the
composition root. ``kpi_analytics.fact_store`` never imports this module.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.kpi_analytics.fact_store.models import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStory,
    PeriodFilter,
    SyncState,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Backend detection (same pattern as project_registration_repository.py)
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    """Return True when the canonical backend is Postgres."""
    from agentkit.state_backend.config import (
        StateBackendKind,
        load_state_backend_config,
    )

    return load_state_backend_config().backend is StateBackendKind.POSTGRES


def _assert_sqlite_allowed() -> None:
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


def _sqlite_db_path(store_dir: Path) -> Path:
    from agentkit.state_backend.config import versioned_sqlite_db_file
    from agentkit.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    from agentkit.state_backend import sqlite_store

    _assert_sqlite_allowed()
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    sqlite_store._ensure_schema(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row

    from agentkit.state_backend import postgres_store
    from agentkit.state_backend.schema_bootstrap import ensure_versioned_schema

    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        ensure_versioned_schema(conn)
        postgres_store._ensure_schema(postgres_store._CompatConnection(conn))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Timestamp binding (TIMESTAMPTZ on Postgres, ISO-8601 TEXT on SQLite)
# ---------------------------------------------------------------------------


def _ts(value: datetime | None, *, is_postgres: bool) -> Any:
    """Bind a timestamp for the target backend.

    Postgres columns are ``TIMESTAMPTZ``: pass the native ``datetime`` so psycopg
    adapts it and the read returns a tz-aware ``datetime``. SQLite stores ISO-8601
    TEXT (no native timestamptz affinity).
    """
    if value is None:
        return None
    return value if is_postgres else value.isoformat()


def _dt(value: Any) -> datetime | None:
    """Reconstruct a ``datetime`` from a Postgres ``datetime`` or SQLite TEXT."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _require_dt(value: Any, column: str) -> datetime:
    parsed = _dt(value)
    if parsed is None:  # pragma: no cover - NOT NULL column, defensive
        raise ValueError(f"{column} must not be NULL")
    return parsed


# ---------------------------------------------------------------------------
# Row <-> model projection (local; no shared mapper truth, like mode_lock)
# ---------------------------------------------------------------------------


def _fact_story_params(fact: FactStory, *, is_postgres: bool) -> dict[str, Any]:
    return {
        "project_key": fact.project_key,
        "story_id": fact.story_id,
        "story_type": fact.story_type,
        "story_size": fact.story_size,
        "story_mode": fact.story_mode,
        "started_at": _ts(fact.started_at, is_postgres=is_postgres),
        "completed_at": _ts(fact.completed_at, is_postgres=is_postgres),
        "qa_rounds": fact.qa_rounds,
        "compaction_count": fact.compaction_count,
        "llm_call_count": fact.llm_call_count,
        "adversarial_findings": fact.adversarial_findings,
        "adversarial_tests_created": fact.adversarial_tests_created,
        "files_changed": fact.files_changed,
        "feedback_converged": _bool_param(
            fact.feedback_converged, is_postgres=is_postgres
        ),
        "phase_setup_ms": fact.phase_setup_ms,
        "phase_implementation_ms": fact.phase_implementation_ms,
        "phase_closure_ms": fact.phase_closure_ms,
        "are_gate_status": fact.are_gate_status,
        "agentkit_version": fact.agentkit_version,
        "agentkit_commit": fact.agentkit_commit,
    }


def _bool_param(value: bool | None, *, is_postgres: bool) -> Any:
    """Bind a nullable boolean (BOOLEAN on Postgres, 0/1 INTEGER on SQLite)."""
    if value is None:
        return None
    return value if is_postgres else int(value)


def _row_to_fact_story(row: dict[str, Any]) -> FactStory:
    feedback = row["feedback_converged"]
    return FactStory(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        story_type=str(row["story_type"]),
        story_size=str(row["story_size"]),
        story_mode=_opt_str(row["story_mode"]),
        started_at=_require_dt(row["started_at"], "fact_story.started_at"),
        completed_at=_dt(row["completed_at"]),
        qa_rounds=int(row["qa_rounds"]),
        compaction_count=_opt_int(row["compaction_count"]),
        llm_call_count=_opt_int(row["llm_call_count"]),
        adversarial_findings=_opt_int(row["adversarial_findings"]),
        adversarial_tests_created=_opt_int(row["adversarial_tests_created"]),
        files_changed=_opt_int(row["files_changed"]),
        feedback_converged=None if feedback is None else bool(feedback),
        phase_setup_ms=_opt_int(row["phase_setup_ms"]),
        phase_implementation_ms=_opt_int(row["phase_implementation_ms"]),
        phase_closure_ms=_opt_int(row["phase_closure_ms"]),
        are_gate_status=_opt_str(row["are_gate_status"]),
        agentkit_version=str(row["agentkit_version"]),
        agentkit_commit=str(row["agentkit_commit"]),
    )


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _row_to_fact_guard(row: dict[str, Any]) -> FactGuardPeriod:
    return FactGuardPeriod(
        project_key=str(row["project_key"]),
        guard_id=str(row["guard_id"]),
        period_start=_require_dt(row["period_start"], "fact_guard_period.period_start"),
        period_end=_require_dt(row["period_end"], "fact_guard_period.period_end"),
        invocation_count=int(row["invocation_count"]),
        violation_count=int(row["violation_count"]),
    )


def _row_to_fact_pool(row: dict[str, Any]) -> FactPoolPeriod:
    return FactPoolPeriod(
        project_key=str(row["project_key"]),
        llm_role=str(row["llm_role"]),
        period_start=_require_dt(row["period_start"], "fact_pool_period.period_start"),
        period_end=_require_dt(row["period_end"], "fact_pool_period.period_end"),
        call_count=int(row["call_count"]),
        token_input_total=int(row["token_input_total"]),
        token_output_total=int(row["token_output_total"]),
        avg_latency_ms=_opt_int(row["avg_latency_ms"]),
    )


def _row_to_fact_pipeline(row: dict[str, Any]) -> FactPipelinePeriod:
    return FactPipelinePeriod(
        project_key=str(row["project_key"]),
        period_start=_require_dt(
            row["period_start"], "fact_pipeline_period.period_start"
        ),
        period_end=_require_dt(row["period_end"], "fact_pipeline_period.period_end"),
        stories_completed=int(row["stories_completed"]),
        stories_escalated=int(row["stories_escalated"]),
        avg_qa_rounds=_opt_float(row["avg_qa_rounds"]),
        avg_phase_implementation_ms=_opt_int(row["avg_phase_implementation_ms"]),
    )


def _row_to_fact_corpus(row: dict[str, Any]) -> FactCorpusPeriod:
    return FactCorpusPeriod(
        project_key=str(row["project_key"]),
        period_start=_require_dt(row["period_start"], "fact_corpus_period.period_start"),
        period_end=_require_dt(row["period_end"], "fact_corpus_period.period_end"),
        incidents_recorded=int(row["incidents_recorded"]),
        patterns_promoted=int(row["patterns_promoted"]),
        checks_approved=int(row["checks_approved"]),
    )


def _row_to_sync_state(row: dict[str, Any]) -> SyncState:
    return SyncState(
        project_key=str(row["project_key"]),
        key=str(row["key"]),
        value_int=_opt_int(row["value_int"]),
        value_text=_opt_str(row["value_text"]),
        updated_at=_require_dt(row["updated_at"], "sync_state.updated_at"),
    )


# ---------------------------------------------------------------------------
# UPSERT statement bodies (shared column lists; placeholders backend-specific)
# ---------------------------------------------------------------------------

_FACT_STORY_COLUMNS = (
    "project_key, story_id, story_type, story_size, story_mode, started_at, "
    "completed_at, qa_rounds, compaction_count, llm_call_count, "
    "adversarial_findings, adversarial_tests_created, files_changed, "
    "feedback_converged, phase_setup_ms, phase_implementation_ms, "
    "phase_closure_ms, are_gate_status, agentkit_version, agentkit_commit"
)
_FACT_STORY_UPDATE = (
    "story_type=excluded.story_type, story_size=excluded.story_size, "
    "story_mode=excluded.story_mode, started_at=excluded.started_at, "
    "completed_at=excluded.completed_at, qa_rounds=excluded.qa_rounds, "
    "compaction_count=excluded.compaction_count, "
    "llm_call_count=excluded.llm_call_count, "
    "adversarial_findings=excluded.adversarial_findings, "
    "adversarial_tests_created=excluded.adversarial_tests_created, "
    "files_changed=excluded.files_changed, "
    "feedback_converged=excluded.feedback_converged, "
    "phase_setup_ms=excluded.phase_setup_ms, "
    "phase_implementation_ms=excluded.phase_implementation_ms, "
    "phase_closure_ms=excluded.phase_closure_ms, "
    "are_gate_status=excluded.are_gate_status, "
    "agentkit_version=excluded.agentkit_version, "
    "agentkit_commit=excluded.agentkit_commit"
)


def _named(columns: str) -> str:
    """Turn ``a, b, c`` into the named-placeholder list ``:a, :b, :c``."""
    return ", ".join(f":{c.strip()}" for c in columns.split(","))


class StateBackendFactRepository:
    """SQLite/Postgres implementation of ``FactRepository`` (AG3-038).

    Backend selected via ``AGENTKIT_STATE_BACKEND``; Postgres is canonical,
    SQLite is the test-parallel path (``AGENTKIT_ALLOW_SQLITE=1``).

    Args:
        store_dir: Base directory for the SQLite store (Postgres ignores it).
            Default: ``Path.cwd()``.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def list_fact_stories(
        self, project_key: str, period: PeriodFilter | None = None
    ) -> list[FactStory]:
        """Return ``fact_story`` rows for ``project_key`` (period bounds completed_at)."""
        if period is None:
            query = (
                "SELECT * FROM fact_story WHERE project_key = ? "
                "ORDER BY story_id"
            )
            params: tuple[Any, ...] = (project_key,)
        else:
            query = (
                "SELECT * FROM fact_story WHERE project_key = ? "
                "AND completed_at >= ? AND completed_at < ? ORDER BY story_id"
            )
            params = (project_key, *self._period_bounds(period))
        return [_row_to_fact_story(r) for r in self._select(query, params)]

    def list_fact_guards(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactGuardPeriod]:
        """Return ``fact_guard_period`` rows for ``project_key`` within ``period``."""
        query = (
            "SELECT * FROM fact_guard_period WHERE project_key = ? "
            "AND period_start >= ? AND period_start < ? "
            "ORDER BY guard_id, period_start"
        )
        params = (project_key, *self._period_bounds(period))
        return [_row_to_fact_guard(r) for r in self._select(query, params)]

    def list_fact_pool(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactPoolPeriod]:
        """Return ``fact_pool_period`` rows for ``project_key`` within ``period``."""
        query = (
            "SELECT * FROM fact_pool_period WHERE project_key = ? "
            "AND period_start >= ? AND period_start < ? "
            "ORDER BY llm_role, period_start"
        )
        params = (project_key, *self._period_bounds(period))
        return [_row_to_fact_pool(r) for r in self._select(query, params)]

    def list_fact_pipeline(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactPipelinePeriod]:
        """Return ``fact_pipeline_period`` rows for ``project_key`` within ``period``."""
        query = (
            "SELECT * FROM fact_pipeline_period WHERE project_key = ? "
            "AND period_start >= ? AND period_start < ? ORDER BY period_start"
        )
        params = (project_key, *self._period_bounds(period))
        return [_row_to_fact_pipeline(r) for r in self._select(query, params)]

    def list_fact_corpus(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactCorpusPeriod]:
        """Return ``fact_corpus_period`` rows for ``project_key`` within ``period``."""
        query = (
            "SELECT * FROM fact_corpus_period WHERE project_key = ? "
            "AND period_start >= ? AND period_start < ? ORDER BY period_start"
        )
        params = (project_key, *self._period_bounds(period))
        return [_row_to_fact_corpus(r) for r in self._select(query, params)]

    def get_sync_state(self, project_key: str, key: str) -> SyncState | None:
        """Return the ``sync_state`` cursor for ``(project_key, key)``, or ``None``.

        Project-scoped per FK-62 §62.2.7 (no global refresh pointer).
        """
        rows = self._select(
            "SELECT * FROM sync_state WHERE project_key = ? AND key = ?",
            (project_key, key),
        )
        return _row_to_sync_state(rows[0]) if rows else None

    def _period_bounds(self, period: PeriodFilter) -> tuple[Any, Any]:
        is_pg = _is_postgres()
        return (
            _ts(period.start, is_postgres=is_pg),
            _ts(period.end, is_postgres=is_pg),
        )

    # ------------------------------------------------------------------
    # upserts (idempotent INSERT-or-replace on the natural PK)
    # ------------------------------------------------------------------

    def upsert_fact_story(self, fact: FactStory) -> None:
        """Insert-or-replace one ``fact_story`` row on ``(project_key, story_id)``."""
        self._upsert(
            table="fact_story",
            columns=_FACT_STORY_COLUMNS,
            conflict="project_key, story_id",
            update_clause=_FACT_STORY_UPDATE,
            params=_fact_story_params(fact, is_postgres=_is_postgres()),
        )

    def upsert_fact_guard(self, fact: FactGuardPeriod) -> None:
        """Insert-or-replace one ``fact_guard_period`` row on its PK."""
        is_pg = _is_postgres()
        self._upsert(
            table="fact_guard_period",
            columns=(
                "project_key, guard_id, period_start, period_end, "
                "invocation_count, violation_count"
            ),
            conflict="project_key, guard_id, period_start",
            update_clause=(
                "period_end=excluded.period_end, "
                "invocation_count=excluded.invocation_count, "
                "violation_count=excluded.violation_count"
            ),
            params={
                "project_key": fact.project_key,
                "guard_id": fact.guard_id,
                "period_start": _ts(fact.period_start, is_postgres=is_pg),
                "period_end": _ts(fact.period_end, is_postgres=is_pg),
                "invocation_count": fact.invocation_count,
                "violation_count": fact.violation_count,
            },
        )

    def upsert_fact_pool(self, fact: FactPoolPeriod) -> None:
        """Insert-or-replace one ``fact_pool_period`` row on its PK."""
        is_pg = _is_postgres()
        self._upsert(
            table="fact_pool_period",
            columns=(
                "project_key, llm_role, period_start, period_end, call_count, "
                "token_input_total, token_output_total, avg_latency_ms"
            ),
            conflict="project_key, llm_role, period_start",
            update_clause=(
                "period_end=excluded.period_end, call_count=excluded.call_count, "
                "token_input_total=excluded.token_input_total, "
                "token_output_total=excluded.token_output_total, "
                "avg_latency_ms=excluded.avg_latency_ms"
            ),
            params={
                "project_key": fact.project_key,
                "llm_role": fact.llm_role,
                "period_start": _ts(fact.period_start, is_postgres=is_pg),
                "period_end": _ts(fact.period_end, is_postgres=is_pg),
                "call_count": fact.call_count,
                "token_input_total": fact.token_input_total,
                "token_output_total": fact.token_output_total,
                "avg_latency_ms": fact.avg_latency_ms,
            },
        )

    def upsert_fact_pipeline(self, fact: FactPipelinePeriod) -> None:
        """Insert-or-replace one ``fact_pipeline_period`` row on its PK."""
        is_pg = _is_postgres()
        self._upsert(
            table="fact_pipeline_period",
            columns=(
                "project_key, period_start, period_end, stories_completed, "
                "stories_escalated, avg_qa_rounds, avg_phase_implementation_ms"
            ),
            conflict="project_key, period_start",
            update_clause=(
                "period_end=excluded.period_end, "
                "stories_completed=excluded.stories_completed, "
                "stories_escalated=excluded.stories_escalated, "
                "avg_qa_rounds=excluded.avg_qa_rounds, "
                "avg_phase_implementation_ms=excluded.avg_phase_implementation_ms"
            ),
            params={
                "project_key": fact.project_key,
                "period_start": _ts(fact.period_start, is_postgres=is_pg),
                "period_end": _ts(fact.period_end, is_postgres=is_pg),
                "stories_completed": fact.stories_completed,
                "stories_escalated": fact.stories_escalated,
                "avg_qa_rounds": fact.avg_qa_rounds,
                "avg_phase_implementation_ms": fact.avg_phase_implementation_ms,
            },
        )

    def upsert_fact_corpus(self, fact: FactCorpusPeriod) -> None:
        """Insert-or-replace one ``fact_corpus_period`` row on its PK."""
        is_pg = _is_postgres()
        self._upsert(
            table="fact_corpus_period",
            columns=(
                "project_key, period_start, period_end, incidents_recorded, "
                "patterns_promoted, checks_approved"
            ),
            conflict="project_key, period_start",
            update_clause=(
                "period_end=excluded.period_end, "
                "incidents_recorded=excluded.incidents_recorded, "
                "patterns_promoted=excluded.patterns_promoted, "
                "checks_approved=excluded.checks_approved"
            ),
            params={
                "project_key": fact.project_key,
                "period_start": _ts(fact.period_start, is_postgres=is_pg),
                "period_end": _ts(fact.period_end, is_postgres=is_pg),
                "incidents_recorded": fact.incidents_recorded,
                "patterns_promoted": fact.patterns_promoted,
                "checks_approved": fact.checks_approved,
            },
        )

    def upsert_sync_state(self, state: SyncState) -> None:
        """Insert-or-replace one ``sync_state`` cursor row on ``(project_key, key)``."""
        is_pg = _is_postgres()
        self._upsert(
            table="sync_state",
            columns="project_key, key, value_int, value_text, updated_at",
            conflict="project_key, key",
            update_clause=(
                "value_int=excluded.value_int, "
                "value_text=excluded.value_text, "
                "updated_at=excluded.updated_at"
            ),
            params={
                "project_key": state.project_key,
                "key": state.key,
                "value_int": state.value_int,
                "value_text": state.value_text,
                "updated_at": _ts(state.updated_at, is_postgres=is_pg),
            },
        )

    # ------------------------------------------------------------------
    # internal engine
    # ------------------------------------------------------------------

    def _select(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        """Run a read query against the active backend, returning row dicts.

        FAIL-CLOSED: a missing table raises the backend's error (no empty-result
        fallback), satisfying story §7.
        """
        if _is_postgres():
            with _postgres_connect() as conn:
                rows = conn.execute(query.replace("?", "%s"), params).fetchall()
            return [dict(r) for r in rows]
        with _sqlite_connect(self._store_dir) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def _upsert(
        self,
        *,
        table: str,
        columns: str,
        conflict: str,
        update_clause: str,
        params: dict[str, Any],
    ) -> None:
        """Execute an idempotent INSERT ... ON CONFLICT DO UPDATE on ``table``."""
        if _is_postgres():
            placeholders = ", ".join(
                f"%({c.strip()})s" for c in columns.split(",")
            )
            statement = (
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict}) DO UPDATE SET {update_clause}"
            )
            with _postgres_connect() as conn:
                conn.execute(statement, params)
            return
        statement = (
            f"INSERT INTO {table} ({columns}) VALUES ({_named(columns)}) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {update_clause}"
        )
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute(statement, params)


__all__ = ["StateBackendFactRepository"]
