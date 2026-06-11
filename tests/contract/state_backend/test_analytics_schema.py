"""Contract tests for the AG3-038 analytics schema (Postgres canonical).

Two contracts (story §2.1.7, AC1/AC2/AC3/AC5):

1. **Schema pinning**: the five fact tables + ``sync_state`` +
   ``guard_invocation_counters`` exist in the active (versioned/test) schema with
   their mandatory columns (queried from ``information_schema.columns``).
2. **Roundtrip + idempotency on Postgres**: insert one row into all five fact
   tables via the FactStore, read them back, and re-upsert ``fact_story`` to prove
   the ON CONFLICT path is idempotent (no duplicate) on the canonical backend.

The contract conftest auto-binds ``postgres_isolated_schema`` to every
``/contract/state_backend/`` item; if no Postgres/Docker is available the fixture
chain raises a clear setup error (same behaviour as the sibling Postgres contract
tests) rather than silently faking a backend. The full SQLite logic is covered by
the unit tests.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg
import pytest
from psycopg import sql

from agentkit.kpi_analytics.fact_store import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStore,
    FactStory,
    PeriodFilter,
    SyncState,
)
from agentkit.state_backend.config import resolve_schema_name
from agentkit.state_backend.store.fact_repository import StateBackendFactRepository

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytest_plugins = ("tests.fixtures.postgres_backend",)

_NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
_LATER = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
_PERIOD = PeriodFilter(start=_NOW, end=datetime(2026, 7, 1, tzinfo=UTC))

# Mandatory columns per table (story §2.1.1 — the binding spec).
_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "fact_story": {
        "project_key",
        "story_id",
        "story_type",
        "story_size",
        "started_at",
        "qa_rounds",
        "agentkit_version",
        "agentkit_commit",
    },
    "fact_guard_period": {
        "project_key",
        "guard_id",
        "period_start",
        "period_end",
        "invocation_count",
        "violation_count",
    },
    "fact_pool_period": {
        "project_key",
        "llm_role",
        "period_start",
        "period_end",
        "call_count",
        "token_input_total",
        "token_output_total",
    },
    "fact_pipeline_period": {
        "project_key",
        "period_start",
        "period_end",
        "stories_completed",
        "stories_escalated",
    },
    "fact_corpus_period": {
        "project_key",
        "period_start",
        "period_end",
        "incidents_recorded",
        "patterns_promoted",
        "checks_approved",
    },
    # FK-62 §62.2.7: project-scoped generic key-value cursor (no global pointer).
    "sync_state": {"project_key", "key", "value_int", "value_text", "updated_at"},
    # FK-62 §62.2.6 / FK-61 §61.4.3: weekly-keyed guard scratchpad.
    "guard_invocation_counters": {
        "project_key",
        "story_id",
        "guard_key",
        "week_start",
        "invocations",
        "blocks",
        "updated_at",
    },
}


@pytest.fixture()
def _pg_conn(postgres_backend_env: str) -> Iterator[psycopg.Connection[object]]:
    """Raw connection on the isolated test schema (for information_schema reads)."""
    schema = resolve_schema_name()
    conn = psycopg.connect(os.environ["AGENTKIT_STATE_DATABASE_URL"], autocommit=True)
    conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
    try:
        yield conn
    finally:
        conn.close()


@pytest.mark.contract
@pytest.mark.parametrize("table", sorted(_REQUIRED_COLUMNS))
def test_analytics_table_exists_with_mandatory_columns(
    _pg_conn: psycopg.Connection[object], table: str
) -> None:
    """AC1/AC2: each analytics table exists with its mandatory columns."""
    schema = resolve_schema_name()
    rows = _pg_conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (schema, table),
    ).fetchall()
    present = {str(r[0]) for r in rows}
    assert present, f"table {table!r} is missing from schema {schema!r}"
    missing = _REQUIRED_COLUMNS[table] - present
    assert not missing, f"{table} missing columns: {sorted(missing)}"


@pytest.mark.contract
def test_fact_story_primary_key_is_project_key_story_id(
    _pg_conn: psycopg.Connection[object],
) -> None:
    """AC1: PK(fact_story) = (project_key, story_id) — Mandantenregel leading."""
    rows = _pg_conn.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = %s
          AND tc.table_name = 'fact_story'
        ORDER BY kcu.ordinal_position
        """,
        (resolve_schema_name(),),
    ).fetchall()
    assert [str(r[0]) for r in rows] == ["project_key", "story_id"]


@pytest.mark.contract
def test_postgres_five_fact_tables_roundtrip_via_factstore(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    """AC3: insert into all five fact tables + read back via FactStore (Postgres)."""
    store = FactStore(StateBackendFactRepository(store_dir=tmp_path))
    store.upsert_fact_story(
        FactStory(
            project_key="pg",
            story_id="AG3-001",
            story_type="implementation",
            story_size="L",
            started_at=_NOW,
            completed_at=_LATER,
            qa_rounds=3,
            feedback_converged=True,
            agentkit_version="3.19.0",
            agentkit_commit="deadbeef",
        )
    )
    store.upsert_fact_guard(
        FactGuardPeriod(
            project_key="pg",
            guard_id="g1",
            period_start=_NOW,
            period_end=_LATER,
            invocation_count=9,
            violation_count=2,
        )
    )
    store.upsert_fact_pool(
        FactPoolPeriod(
            project_key="pg",
            llm_role="worker",
            period_start=_NOW,
            period_end=_LATER,
            call_count=4,
            token_input_total=200,
            token_output_total=80,
            avg_latency_ms=300,
        )
    )
    store.upsert_fact_pipeline(
        FactPipelinePeriod(
            project_key="pg",
            period_start=_NOW,
            period_end=_LATER,
            stories_completed=2,
            stories_escalated=1,
            avg_qa_rounds=2.5,
        )
    )
    store.upsert_fact_corpus(
        FactCorpusPeriod(
            project_key="pg",
            period_start=_NOW,
            period_end=_LATER,
            incidents_recorded=1,
            patterns_promoted=0,
            checks_approved=0,
        )
    )

    stories = store.list_fact_stories("pg")
    assert len(stories) == 1
    assert stories[0].feedback_converged is True
    assert stories[0].started_at == _NOW
    assert stories[0].started_at.tzinfo is not None
    assert store.list_fact_guards("pg", _PERIOD)[0].violation_count == 2
    assert store.list_fact_pool("pg", _PERIOD)[0].avg_latency_ms == 300
    assert store.list_fact_pipeline("pg", _PERIOD)[0].avg_qa_rounds == 2.5
    assert store.list_fact_corpus("pg", _PERIOD)[0].incidents_recorded == 1


@pytest.mark.contract
def test_postgres_upsert_fact_story_is_idempotent(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    """AC5: re-upsert on the same PK updates in place (no duplicate) on Postgres."""
    store = FactStore(StateBackendFactRepository(store_dir=tmp_path))

    def _story(qa: int) -> FactStory:
        return FactStory(
            project_key="pg",
            story_id="AG3-009",
            story_type="implementation",
            story_size="M",
            started_at=_NOW,
            qa_rounds=qa,
            agentkit_version="3.19.0",
            agentkit_commit="deadbeef",
        )

    store.upsert_fact_story(_story(3))
    store.upsert_fact_story(_story(7))
    rows = store.list_fact_stories("pg")
    assert len(rows) == 1
    assert rows[0].qa_rounds == 7


@pytest.mark.contract
def test_postgres_sync_state_is_project_scoped_key_value(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    """FK-62 §62.2.7: sync_state is a project-scoped (project_key, key) cursor.

    No global refresh pointer: the same ``key`` under two projects is two
    distinct rows, and a read is scoped to one project.
    """
    store = FactStore(StateBackendFactRepository(store_dir=tmp_path))
    assert store.get_sync_state("pg", "last_event_id") is None
    store.upsert_sync_state(
        SyncState(
            project_key="pg",
            key="last_event_id",
            value_text="22222222-2222-2222-2222-222222222222",
            updated_at=_NOW,
        )
    )
    store.upsert_sync_state(
        SyncState(
            project_key="pg-other",
            key="last_event_id",
            value_text="99999999-9999-9999-9999-999999999999",
            updated_at=_NOW,
        )
    )
    loaded = store.get_sync_state("pg", "last_event_id")
    assert loaded is not None
    assert loaded.value_text == "22222222-2222-2222-2222-222222222222"
    other = store.get_sync_state("pg-other", "last_event_id")
    assert other is not None
    assert other.value_text == "99999999-9999-9999-9999-999999999999"


@pytest.mark.contract
def test_sync_state_primary_key_is_project_key_and_key(
    _pg_conn: psycopg.Connection[object],
) -> None:
    """FK-62 §62.2.7: PK(sync_state) = (project_key, key) — Mandantenregel leading."""
    rows = _pg_conn.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = %s
          AND tc.table_name = 'sync_state'
        ORDER BY kcu.ordinal_position
        """,
        (resolve_schema_name(),),
    ).fetchall()
    assert [str(r[0]) for r in rows] == ["project_key", "key"]


@pytest.mark.contract
def test_guard_invocation_counters_primary_key_is_weekly_scratchpad(
    _pg_conn: psycopg.Connection[object],
) -> None:
    """FK-62 §62.2.6 / FK-61 §61.4.3: PK = (project_key, story_id, guard_key, week_start)."""
    rows = _pg_conn.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = %s
          AND tc.table_name = 'guard_invocation_counters'
        ORDER BY kcu.ordinal_position
        """,
        (resolve_schema_name(),),
    ).fetchall()
    assert [str(r[0]) for r in rows] == [
        "project_key",
        "story_id",
        "guard_key",
        "week_start",
    ]


@pytest.mark.contract
def test_postgres_write_session_replace_delete_and_rollback(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    """AG3-082 AC4/AC11: the atomic write session DELETE+INSERT replace + rollback (Postgres).

    Proves the new FK-62 §62.3.2 ports on the canonical backend: a clean session
    replaces a period slice and deletes ``fact_story`` (commit on exit), and a
    failing session rolls the WHOLE transaction back (no partial commit).
    """
    store = FactStore(StateBackendFactRepository(store_dir=tmp_path))
    repo = StateBackendFactRepository(store_dir=tmp_path)
    store.upsert_fact_story(
        FactStory(
            project_key="pg",
            story_id="AG3-200",
            story_type="implementation",
            story_size="L",
            started_at=_NOW,
            qa_rounds=1,
            agentkit_version="3.20.0",
            agentkit_commit="abc",
        )
    )
    store.upsert_fact_pool(
        FactPoolPeriod(
            project_key="pg",
            llm_role="qa",
            period_start=_NOW,
            period_end=_LATER,
            call_count=1,
            token_input_total=1,
            token_output_total=1,
        )
    )

    replacement = FactPoolPeriod(
        project_key="pg",
        llm_role="qa",
        period_start=_NOW,
        period_end=_LATER,
        call_count=42,
        token_input_total=9,
        token_output_total=9,
    )
    with repo.begin_write_session() as session:
        session.replace_pool_period([("pg", "qa", _NOW)], [replacement])
        session.delete_fact_story("pg", "AG3-200")

    assert store.list_fact_pool("pg", _PERIOD)[0].call_count == 42
    assert store.list_fact_stories("pg") == []

    # Rollback: an exception inside the session reverts every write.
    with pytest.raises(RuntimeError, match="boom"), repo.begin_write_session() as session:
        session.replace_pool_period(
            [("pg", "qa", _NOW)],
            [replacement.model_copy(update={"call_count": 7})],
        )
        raise RuntimeError("boom")

    # The committed value survives; the rolled-back replace did not take effect.
    assert store.list_fact_pool("pg", _PERIOD)[0].call_count == 42


@pytest.mark.contract
def test_postgres_init_runs_migration_and_records_schema_version(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    """FIX-3: normal backend init wires the MigrationRunner and records 3.4.

    Opening a FactStore connection runs the canonical bootstrap, which invokes
    the MigrationRunner; the ``schema_versions`` cursor must then carry
    version ``3.4`` (FK-62 §62.4.3) — proving the runner is live in production,
    not dead module/test-only code.
    """
    # A read triggers the full connection bootstrap on the isolated schema.
    store = FactStore(StateBackendFactRepository(store_dir=tmp_path))
    assert store.get_sync_state("pg", "schema_version") is None
    schema = resolve_schema_name()
    conn = psycopg.connect(os.environ["AGENTKIT_STATE_DATABASE_URL"], autocommit=True)
    try:
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        rows = conn.execute(
            "SELECT version FROM schema_versions WHERE version = '3.4'"
        ).fetchall()
    finally:
        conn.close()
    assert [str(r[0]) for r in rows] == ["3.4"]
