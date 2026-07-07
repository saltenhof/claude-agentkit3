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

import ast
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
import pytest
from psycopg import sql

from agentkit.backend.kpi_analytics.fact_store import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStore,
    FactStory,
    PeriodFilter,
    SyncState,
)
from agentkit.backend.state_backend.config import resolve_schema_name
from agentkit.backend.state_backend.store.fact_repository import StateBackendFactRepository

if TYPE_CHECKING:
    from collections.abc import Iterator

pytest_plugins = ("tests.fixtures.postgres_backend",)

_NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
_LATER = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
_PERIOD = PeriodFilter(start=_NOW, end=datetime(2026, 7, 1, tzinfo=UTC))

# FK-62 §62.2.1-62.2.5 reconciled column sets (AG3-117). These are the EXACT
# FK-62 column sets per fact table (not a subset): the truth-location-identity
# contract (test_fact_schema_column_sets_are_identical_across_truth_locations)
# pins them against models / _fact_sql / fact_repository.
_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "fact_story": {
        "project_key",
        "story_id",
        "story_type",
        "story_size",
        "pipeline_mode",
        "opened_at",
        "closed_at",
        "processing_time_ms",
        "compaction_count",
        "qa_round_count",
        "feedback_converged",
        "blocked_ac_count",
        "blocked_ac_detail_json",
        "llm_call_count",
        "adversarial_findings_count",
        "adversarial_tests_created",
        "adversarial_hit_rate",
        "findings_fully_resolved",
        "findings_partially_resolved",
        "findings_not_resolved",
        "final_status",
        "are_gate_passed",
        "are_total_requirements",
        "are_covered_requirements",
        "files_changed",
        "increment_count",
        "phase_setup_ms",
        "phase_exploration_ms",
        "phase_implementation_ms",
        "phase_verify_ms",
        "phase_closure_ms",
        "computed_at",
    },
    "fact_guard_period": {
        "project_key",
        "guard_key",
        "period_start",
        "period_grain",
        "invocation_count",
        "violation_count",
        "violation_rate",
        "violation_stage_escape",
        "violation_stage_schema",
        "violation_stage_template",
        "escape_detection_count",
        "computed_at",
    },
    "fact_pool_period": {
        "project_key",
        "pool_key",
        "period_start",
        "period_grain",
        "call_count",
        "response_time_p50_ms",
        "verdict_adopted_count",
        "verdict_total_count",
        "finding_true_positive_count",
        "finding_false_positive_count",
        "quorum_triggered_count",
        "template_finding_rate_json",
        "computed_at",
    },
    "fact_pipeline_period": {
        "project_key",
        "period_start",
        "period_grain",
        "story_count",
        "story_count_closed",
        "execution_count",
        "exploration_count",
        "stage_miss_count",
        "stage_miss_detail_json",
        "impact_violation_count",
        "impact_check_count",
        "integrity_gate_block_count",
        "integrity_gate_total_count",
        "doc_fidelity_conflict_by_level_json",
        "first_pass_count",
        "finding_survival_count",
        "finding_total_count",
        "effective_check_ids_json",
        "vectordb_total_hits",
        "vectordb_above_threshold",
        "vectordb_classified_conflict",
        "vectordb_duplicate_detected",
        "processing_time_avg_ms",
        "processing_time_variance_ms2",
        "qa_round_avg",
        "computed_at",
    },
    "fact_corpus_period": {
        "project_key",
        "period_start",
        "period_grain",
        "new_incident_count",
        "patterns_total_count",
        "patterns_with_active_check",
        "computed_at",
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

# FK-62 fact tables whose column set must be IDENTICAL across all truth-locations
# (AG3-117 AC2). ``response_time_p95_ms`` is INVENTAR (FK-62 §62.2.3) — absent.
_FACT_TABLES: tuple[str, ...] = (
    "fact_story",
    "fact_guard_period",
    "fact_pool_period",
    "fact_pipeline_period",
    "fact_corpus_period",
)


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
            opened_at=_NOW,
            closed_at=_LATER,
            qa_round_count=3,
            feedback_converged=True,
            are_gate_passed=True,
            computed_at=_LATER,
        )
    )
    store.upsert_fact_guard(
        FactGuardPeriod(
            project_key="pg",
            guard_key="g1",
            period_start=_NOW,
            invocation_count=9,
            violation_count=2,
            computed_at=_LATER,
        )
    )
    store.upsert_fact_pool(
        FactPoolPeriod(
            project_key="pg",
            pool_key="worker",
            period_start=_NOW,
            call_count=4,
            response_time_p50_ms=300,
            computed_at=_LATER,
        )
    )
    store.upsert_fact_pipeline(
        FactPipelinePeriod(
            project_key="pg",
            period_start=_NOW,
            story_count=3,
            story_count_closed=2,
            qa_round_avg=2.5,
            computed_at=_LATER,
        )
    )
    store.upsert_fact_corpus(
        FactCorpusPeriod(
            project_key="pg",
            period_start=_NOW,
            new_incident_count=1,
            computed_at=_LATER,
        )
    )

    stories = store.list_fact_stories("pg")
    assert len(stories) == 1
    assert stories[0].feedback_converged is True
    assert stories[0].are_gate_passed is True
    assert stories[0].opened_at == _NOW
    assert stories[0].opened_at.tzinfo is not None
    assert store.list_fact_guards("pg", _PERIOD)[0].violation_count == 2
    assert store.list_fact_pool("pg", _PERIOD)[0].response_time_p50_ms == 300
    assert store.list_fact_pipeline("pg", _PERIOD)[0].qa_round_avg == 2.5
    assert store.list_fact_corpus("pg", _PERIOD)[0].new_incident_count == 1


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
            opened_at=_NOW,
            qa_round_count=qa,
            computed_at=_NOW,
        )

    store.upsert_fact_story(_story(3))
    store.upsert_fact_story(_story(7))
    rows = store.list_fact_stories("pg")
    assert len(rows) == 1
    assert rows[0].qa_round_count == 7


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
            opened_at=_NOW,
            qa_round_count=1,
            computed_at=_NOW,
        )
    )
    store.upsert_fact_pool(
        FactPoolPeriod(
            project_key="pg",
            pool_key="qa",
            period_start=_NOW,
            call_count=1,
            computed_at=_LATER,
        )
    )

    replacement = FactPoolPeriod(
        project_key="pg",
        pool_key="qa",
        period_start=_NOW,
        call_count=42,
        computed_at=_LATER,
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
    """AG3-117: normal backend init wires the MigrationRunner up to head 3.6.

    Opening a FactStore connection runs the canonical bootstrap, which invokes
    the MigrationRunner; the ``schema_versions`` cursor must then carry the full
    forward chain ``3.4`` / ``3.5`` / ``3.6`` (FK-62 §62.4.3), with ``3.6``
    (the AG3-117 fact reconciliation) as the recorded head — proving the runner
    is live in production, not dead module/test-only code.
    """
    # A read triggers the full connection bootstrap on the isolated schema.
    store = FactStore(StateBackendFactRepository(store_dir=tmp_path))
    assert store.get_sync_state("pg", "schema_version") is None
    schema = resolve_schema_name()
    conn = psycopg.connect(os.environ["AGENTKIT_STATE_DATABASE_URL"], autocommit=True)
    try:
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        rows = conn.execute(
            "SELECT version FROM schema_versions "
            "WHERE version IN ('3.4', '3.5', '3.6') ORDER BY version"
        ).fetchall()
    finally:
        conn.close()
    assert [str(r[0]) for r in rows] == ["3.4", "3.5", "3.6"]


def test_reconciliation_is_column_conditional_drop_not_create_if_not_exists() -> None:
    """AG3-117 Finding 1 (STATIC): an existing-OLD PG fact table is reconciled.

    Docker-free static guarantee. The Postgres apply path runs on EVERY connection,
    so reconciliation cannot rely on ``CREATE TABLE IF NOT EXISTS`` alone (that would
    never touch a pre-AG3-117 table). The guarantee is provided by
    ``postgres_store._reconcile_fact_tables_fk62`` running BEFORE the schema script
    and emitting, per fact table, a column-set-CONDITIONAL ``DROP TABLE ... CASCADE``
    (drops ONLY when the existing column set differs from FK-62 — so an old table is
    rebuilt FK-62-shaped while an already-FK-62 table is NOT wiped each startup).
    """
    from agentkit.backend.state_backend.postgres_store import _schema

    source = Path(_schema.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_reconcile_fact_tables_fk62"
    )
    body_text = ast.get_source_segment(source, func) or ""

    # _ensure_schema must run the reconciliation BEFORE applying the schema script.
    ensure = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_ensure_schema"
    )
    ensure_calls = [
        n.func.id
        for n in ast.walk(ensure)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert "_reconcile_fact_tables_fk62" in ensure_calls
    assert ensure_calls.index("_reconcile_fact_tables_fk62") < ensure_calls.index(
        "_schema_create_script"
    ), "reconciliation must run before the schema-create script"

    # A column-conditional CASCADE drop (NOT a bare CREATE IF NOT EXISTS), gated on
    # the information_schema column-set comparison. The DROP target is the per-table
    # ``{table}`` f-string slot, fed from the fixed five-table loop below.
    assert "DROP TABLE IF EXISTS {table} CASCADE" in body_text
    assert "information_schema.columns" in body_text
    assert "IS DISTINCT FROM" in body_text

    # The drop is restricted to exactly the five disposable fact_* rollups: the loop
    # iterates ``_FACT_TABLE_NAMES``, parsed here from the module-level assignment.
    names_assign = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "_FACT_TABLE_NAMES"
    )
    assert isinstance(names_assign.value, ast.Tuple)
    looped_tables = {
        str(elt.value)
        for elt in names_assign.value.elts
        if isinstance(elt, ast.Constant)
    }
    assert looped_tables == set(_FACT_TABLES), looped_tables


@pytest.mark.contract
def test_postgres_existing_old_fact_table_is_reconciled_to_fk62(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    """AG3-117 Finding 1 (LIVE): a pre-AG3-117 ``fact_story`` reconciles to FK-62.

    Seeds the isolated schema with an OLD-shaped ``fact_story`` (the AG3-038
    ``started_at`` / ``completed_at`` / ``qa_rounds`` columns, no ``closed_at`` /
    ``are_gate_passed``), then opens a normal FactStore connection. The
    column-conditional reconciliation must DROP+rebuild the table onto the FK-62
    column set (so the ``closed_at`` index applies) — proving an existing-old PG is
    brought to FK-62 regardless of prior state.
    """
    schema = resolve_schema_name()
    conn = psycopg.connect(os.environ["AGENTKIT_STATE_DATABASE_URL"], autocommit=True)
    try:
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        # Replace the freshly-bootstrapped FK-62 table with the OLD AG3-038 shape.
        conn.execute("DROP TABLE IF EXISTS fact_story CASCADE")
        conn.execute(
            "CREATE TABLE fact_story ("
            "project_key TEXT NOT NULL, story_id TEXT NOT NULL, "
            "started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, qa_rounds BIGINT, "
            "PRIMARY KEY (project_key, story_id))"
        )
    finally:
        conn.close()

    # A read opens a normal connection -> _ensure_schema -> reconciliation runs.
    store = FactStore(StateBackendFactRepository(store_dir=tmp_path))
    assert store.list_fact_stories("pg") == []

    conn = psycopg.connect(os.environ["AGENTKIT_STATE_DATABASE_URL"], autocommit=True)
    try:
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'fact_story'",
            (schema,),
        ).fetchall()
    finally:
        conn.close()
    present = {str(r[0]) for r in rows}
    assert present == _REQUIRED_COLUMNS["fact_story"], "fact_story not reconciled to FK-62"
    # The OLD-only columns are gone; the FK-62-only columns are present.
    assert "qa_rounds" not in present
    assert "closed_at" in present
    assert "are_gate_passed" in present


@pytest.mark.contract
def test_fact_pool_period_has_p50_but_not_p95(
    _pg_conn: psycopg.Connection[object],
) -> None:
    """AC7: fact_pool_period carries response_time_p50_ms; p95 stays INVENTAR."""
    schema = resolve_schema_name()
    rows = _pg_conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = 'fact_pool_period'",
        (schema,),
    ).fetchall()
    present = {str(r[0]) for r in rows}
    assert "response_time_p50_ms" in present
    assert "response_time_p95_ms" not in present


def _columns_of(column_list: str) -> set[str]:
    """Split a ``a, b, c`` _fact_sql column string into a name set."""
    return {c.strip() for c in column_list.split(",")}


# --- AG3-117 (Finding 2): real parsers for the remaining truth-locations ------
# AC2 requires the FK-62 column set to be IDENTICAL across ALL FIVE truth-locations.
# The model fields and the ``_fact_sql`` UPSERT lists are read directly above; the
# three below are PARSED from source (no hardcoded expected set) so drift in ANY one
# of them turns this contract red:
#   3) ``fact_repository``  — the mapper ``_fact_*_params`` dict keys AND the
#      ``_row_to_fact_*`` ``row["..."]`` read keys.
#   4) ``postgres_schema.sql`` — the ``CREATE TABLE ... fact_* (...)`` column list.
#   5) ``v_3_6_fact_reconciliation.sql`` — the SQLite ``CREATE TABLE`` column list.

#: ``fact_repository`` function-name pair (params-mapper, row-reader) per table.
_FACT_REPO_FUNCS: dict[str, tuple[str, str]] = {
    "fact_story": ("_fact_story_params", "_row_to_fact_story"),
    "fact_guard_period": ("_fact_guard_params", "_row_to_fact_guard"),
    "fact_pool_period": ("_fact_pool_params", "_row_to_fact_pool"),
    "fact_pipeline_period": ("_fact_pipeline_params", "_row_to_fact_pipeline"),
    "fact_corpus_period": ("_fact_corpus_params", "_row_to_fact_corpus"),
}

#: Non-column tokens that may appear inside a ``CREATE TABLE`` body.
_DDL_NON_COLUMN_PREFIXES = ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT")


def _params_dict_keys(func: ast.FunctionDef) -> set[str]:
    """Return the string keys of the single dict the params-mapper returns."""
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            keys: set[str] = set()
            for key in node.value.keys:
                assert isinstance(key, ast.Constant), f"non-literal key in {func.name}"
                keys.add(str(key.value))
            return keys
    raise AssertionError(f"{func.name}: no dict return found")


def _row_subscript_keys(func: ast.FunctionDef) -> set[str]:
    """Return every ``row["<col>"]`` literal subscript key read in the row-reader."""
    keys: set[str] = set()
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "row"
            and isinstance(node.slice, ast.Constant)
        ):
            keys.add(str(node.slice.value))
    return keys


def _fact_repository_keys(table: str) -> tuple[set[str], set[str]]:
    """Parse ``fact_repository`` for the params-mapper + row-reader column keys."""
    from agentkit.backend.state_backend.store import fact_repository

    source = Path(fact_repository.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    funcs = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    params_name, row_name = _FACT_REPO_FUNCS[table]
    return (
        _params_dict_keys(funcs[params_name]),
        _row_subscript_keys(funcs[row_name]),
    )


def _ddl_table_columns(sql_text: str, table: str) -> set[str]:
    """Parse the column names from the ``CREATE TABLE [IF NOT EXISTS] <table> (...)``.

    Reads the FIRST identifier of each definition line inside the parenthesised
    body, skipping table-level constraint clauses (PRIMARY KEY, ...). The parser is
    REAL (no hardcoded expectation); it raises if the table block is absent so a
    renamed/removed table cannot pass silently.
    """
    pattern = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + re.escape(table) + r"\s*\(",
        re.IGNORECASE,
    )
    match = pattern.search(sql_text)
    if match is None:  # pragma: no cover - defensive: a missing block fails loudly
        raise AssertionError(f"{table}: CREATE TABLE block not found")
    depth = 1
    i = match.end()
    while i < len(sql_text) and depth > 0:
        if sql_text[i] == "(":
            depth += 1
        elif sql_text[i] == ")":
            depth -= 1
        i += 1
    body = sql_text[match.end() : i - 1]
    columns: set[str] = set()
    for raw_line in body.split("\n"):
        line = raw_line.strip().rstrip(",")
        if not line or line.startswith("--"):
            continue
        first = line.split()[0]
        if first.upper() in _DDL_NON_COLUMN_PREFIXES:
            continue
        columns.add(first)
    return columns


def _postgres_schema_columns(table: str) -> set[str]:
    from agentkit.backend.state_backend import postgres_store

    sql_text = Path(postgres_store.__file__).with_name("postgres_schema.sql").read_text(
        encoding="utf-8",
    )
    return _ddl_table_columns(sql_text, table)


def _v36_migration_columns(table: str) -> set[str]:
    from agentkit.backend.state_backend.migration import migration_runner

    sql_text = (
        Path(migration_runner.__file__).with_name("versions")
        / "v_3_6_fact_reconciliation.sql"
    ).read_text(encoding="utf-8")
    return _ddl_table_columns(sql_text, table)


@pytest.mark.contract
@pytest.mark.parametrize("table", _FACT_TABLES)
def test_fact_schema_column_sets_are_identical_across_truth_locations(
    table: str,
) -> None:
    """AC2: the FK-62 column set is IDENTICAL across every truth-location.

    Five truth-locations, each PARSED from its own source (not hardcoded to the
    expected set), pinned against ONE FK-62 set per table — drift at any single
    location turns this contract red:

    1. the Pydantic model fields,
    2. the ``_fact_sql`` UPSERT column list,
    3. ``fact_repository``'s ``_fact_*_params`` mapper keys AND ``_row_to_*`` reads,
    4. the ``postgres_schema.sql`` ``CREATE TABLE`` column list,
    5. the ``v_3_6_fact_reconciliation.sql`` ``CREATE TABLE`` column list.
    """
    from agentkit.backend.kpi_analytics.fact_store import models as _models
    from agentkit.backend.state_backend.store import _fact_sql

    model_cls = {
        "fact_story": _models.FactStory,
        "fact_guard_period": _models.FactGuardPeriod,
        "fact_pool_period": _models.FactPoolPeriod,
        "fact_pipeline_period": _models.FactPipelinePeriod,
        "fact_corpus_period": _models.FactCorpusPeriod,
    }[table]
    sql_columns = {
        "fact_story": _fact_sql._FACT_STORY_COLUMNS,
        "fact_guard_period": _fact_sql._FACT_GUARD_COLUMNS,
        "fact_pool_period": _fact_sql._FACT_POOL_COLUMNS,
        "fact_pipeline_period": _fact_sql._FACT_PIPELINE_COLUMNS,
        "fact_corpus_period": _fact_sql._FACT_CORPUS_COLUMNS,
    }[table]

    expected = _REQUIRED_COLUMNS[table]
    model_fields = set(model_cls.model_fields)
    repo_params, repo_rows = _fact_repository_keys(table)
    pg_ddl = _postgres_schema_columns(table)
    v36_ddl = _v36_migration_columns(table)

    assert model_fields == expected, f"{table}: model fields drift"
    assert _columns_of(sql_columns) == expected, f"{table}: _fact_sql columns drift"
    assert repo_params == expected, f"{table}: fact_repository params-mapper drift"
    assert repo_rows == expected, f"{table}: fact_repository row-reader drift"
    assert pg_ddl == expected, f"{table}: postgres_schema.sql DDL drift"
    assert v36_ddl == expected, f"{table}: v_3_6 migration DDL drift"
