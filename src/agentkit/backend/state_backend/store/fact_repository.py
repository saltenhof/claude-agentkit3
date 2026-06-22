"""StateBackendFactRepository — analytics fact-table persistence (AG3-038).

Productive SQLite/Postgres implementation of the consumer-owned
``FactRepository`` Protocol (``agentkit.backend.kpi_analytics.fact_store.repository``),
backing the FactStore (FK-62 §62.3). Mirrors ``project_registration_repository``:

- Postgres is the canonical truth (FK-60 §60.3.2); SQLite is the test-only
  parallel path (``AGENTKIT_ALLOW_SQLITE=1``). No co-equal dual-backend run.
- Analytics DDL has ONE authoritative path per backend: the typed Postgres truth
  is ``postgres_schema.sql``; the SQLite truth is the versioned migration chain
  applied by the ``MigrationRunner`` (FK-62 §62.4) from
  ``sqlite_store._ensure_analytics_tables`` — v_3_4 introduced the analytics
  tables, v_3_6 (AG3-117) drops+rebuilds the five ``fact_*`` tables onto the
  FK-62 §62.2 column set. Both bootstraps also run the MigrationRunner so it
  records the logical analytics versions in the idempotent ``schema_versions``
  cursor (head 3.6) — wired in production, not dead code.
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

from agentkit.backend.kpi_analytics.fact_store.models import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStory,
    GuardInvocationCounter,
    PeriodFilter,
    SyncState,
)
from agentkit.backend.state_backend.store._fact_sql import (
    _FACT_CORPUS_COLUMNS,
    _FACT_CORPUS_CONFLICT,
    _FACT_CORPUS_UPDATE,
    _FACT_GUARD_COLUMNS,
    _FACT_GUARD_CONFLICT,
    _FACT_GUARD_UPDATE,
    _FACT_PIPELINE_COLUMNS,
    _FACT_PIPELINE_CONFLICT,
    _FACT_PIPELINE_UPDATE,
    _FACT_POOL_COLUMNS,
    _FACT_POOL_CONFLICT,
    _FACT_POOL_UPDATE,
    _FACT_STORY_COLUMNS,
    _FACT_STORY_UPDATE,
    _SYNC_STATE_COLUMNS,
    _SYNC_STATE_CONFLICT,
    _SYNC_STATE_UPDATE,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


# ---------------------------------------------------------------------------
# Backend detection (same pattern as project_registration_repository.py)
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    """Return True when the canonical backend is Postgres."""
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


def _postgres_database_url() -> str:
    url = os.environ.get("AGENTKIT_STATE_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "AGENTKIT_STATE_DATABASE_URL must be set when "
            "AGENTKIT_STATE_BACKEND=postgres"
        )
    return url


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

    from agentkit.backend.state_backend import postgres_store
    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        ensure_versioned_schema(conn)
        postgres_store._ensure_schema_once(postgres_store._CompatConnection(conn))
        conn.commit()
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
        "pipeline_mode": fact.pipeline_mode,
        "opened_at": _ts(fact.opened_at, is_postgres=is_postgres),
        "closed_at": _ts(fact.closed_at, is_postgres=is_postgres),
        "processing_time_ms": fact.processing_time_ms,
        "compaction_count": fact.compaction_count,
        "qa_round_count": fact.qa_round_count,
        "feedback_converged": _bool_param(
            fact.feedback_converged, is_postgres=is_postgres
        ),
        "blocked_ac_count": fact.blocked_ac_count,
        "blocked_ac_detail_json": fact.blocked_ac_detail_json,
        "llm_call_count": fact.llm_call_count,
        "adversarial_findings_count": fact.adversarial_findings_count,
        "adversarial_tests_created": fact.adversarial_tests_created,
        "adversarial_hit_rate": fact.adversarial_hit_rate,
        "findings_fully_resolved": fact.findings_fully_resolved,
        "findings_partially_resolved": fact.findings_partially_resolved,
        "findings_not_resolved": fact.findings_not_resolved,
        "final_status": fact.final_status,
        "are_gate_passed": _bool_param(
            fact.are_gate_passed, is_postgres=is_postgres
        ),
        "are_total_requirements": fact.are_total_requirements,
        "are_covered_requirements": fact.are_covered_requirements,
        "files_changed": fact.files_changed,
        "increment_count": fact.increment_count,
        "phase_setup_ms": fact.phase_setup_ms,
        "phase_exploration_ms": fact.phase_exploration_ms,
        "phase_implementation_ms": fact.phase_implementation_ms,
        "phase_verify_ms": fact.phase_verify_ms,
        "phase_closure_ms": fact.phase_closure_ms,
        "computed_at": _ts(fact.computed_at, is_postgres=is_postgres),
    }


def _bool_param(value: bool | None, *, is_postgres: bool) -> Any:
    """Bind a nullable boolean (BOOLEAN on Postgres, 0/1 INTEGER on SQLite)."""
    if value is None:
        return None
    return value if is_postgres else int(value)


def _fact_guard_params(fact: FactGuardPeriod, *, is_postgres: bool) -> dict[str, Any]:
    return {
        "project_key": fact.project_key,
        "guard_key": fact.guard_key,
        "period_start": _ts(fact.period_start, is_postgres=is_postgres),
        "period_grain": fact.period_grain,
        "invocation_count": fact.invocation_count,
        "violation_count": fact.violation_count,
        "violation_rate": fact.violation_rate,
        "violation_stage_escape": fact.violation_stage_escape,
        "violation_stage_schema": fact.violation_stage_schema,
        "violation_stage_template": fact.violation_stage_template,
        "escape_detection_count": fact.escape_detection_count,
        "computed_at": _ts(fact.computed_at, is_postgres=is_postgres),
    }


def _fact_pool_params(fact: FactPoolPeriod, *, is_postgres: bool) -> dict[str, Any]:
    return {
        "project_key": fact.project_key,
        "pool_key": fact.pool_key,
        "period_start": _ts(fact.period_start, is_postgres=is_postgres),
        "period_grain": fact.period_grain,
        "call_count": fact.call_count,
        "response_time_p50_ms": fact.response_time_p50_ms,
        "verdict_adopted_count": fact.verdict_adopted_count,
        "verdict_total_count": fact.verdict_total_count,
        "finding_true_positive_count": fact.finding_true_positive_count,
        "finding_false_positive_count": fact.finding_false_positive_count,
        "quorum_triggered_count": fact.quorum_triggered_count,
        "template_finding_rate_json": fact.template_finding_rate_json,
        "computed_at": _ts(fact.computed_at, is_postgres=is_postgres),
    }


def _fact_pipeline_params(
    fact: FactPipelinePeriod, *, is_postgres: bool
) -> dict[str, Any]:
    return {
        "project_key": fact.project_key,
        "period_start": _ts(fact.period_start, is_postgres=is_postgres),
        "period_grain": fact.period_grain,
        "story_count": fact.story_count,
        "story_count_closed": fact.story_count_closed,
        "execution_count": fact.execution_count,
        "exploration_count": fact.exploration_count,
        "stage_miss_count": fact.stage_miss_count,
        "stage_miss_detail_json": fact.stage_miss_detail_json,
        "impact_violation_count": fact.impact_violation_count,
        "impact_check_count": fact.impact_check_count,
        "integrity_gate_block_count": fact.integrity_gate_block_count,
        "integrity_gate_total_count": fact.integrity_gate_total_count,
        "doc_fidelity_conflict_by_level_json": (
            fact.doc_fidelity_conflict_by_level_json
        ),
        "first_pass_count": fact.first_pass_count,
        "finding_survival_count": fact.finding_survival_count,
        "finding_total_count": fact.finding_total_count,
        "effective_check_ids_json": fact.effective_check_ids_json,
        "vectordb_total_hits": fact.vectordb_total_hits,
        "vectordb_above_threshold": fact.vectordb_above_threshold,
        "vectordb_classified_conflict": fact.vectordb_classified_conflict,
        "vectordb_duplicate_detected": fact.vectordb_duplicate_detected,
        "processing_time_avg_ms": fact.processing_time_avg_ms,
        "processing_time_variance_ms2": fact.processing_time_variance_ms2,
        "qa_round_avg": fact.qa_round_avg,
        "computed_at": _ts(fact.computed_at, is_postgres=is_postgres),
    }


def _fact_corpus_params(
    fact: FactCorpusPeriod, *, is_postgres: bool
) -> dict[str, Any]:
    return {
        "project_key": fact.project_key,
        "period_start": _ts(fact.period_start, is_postgres=is_postgres),
        "period_grain": fact.period_grain,
        "new_incident_count": fact.new_incident_count,
        "patterns_total_count": fact.patterns_total_count,
        "patterns_with_active_check": fact.patterns_with_active_check,
        "computed_at": _ts(fact.computed_at, is_postgres=is_postgres),
    }


def _row_to_fact_story(row: dict[str, Any]) -> FactStory:
    return FactStory(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        story_type=str(row["story_type"]),
        story_size=str(row["story_size"]),
        pipeline_mode=_opt_str(row["pipeline_mode"]),
        opened_at=_require_dt(row["opened_at"], "fact_story.opened_at"),
        closed_at=_dt(row["closed_at"]),
        processing_time_ms=_opt_int(row["processing_time_ms"]),
        compaction_count=int(row["compaction_count"]),
        qa_round_count=int(row["qa_round_count"]),
        feedback_converged=_opt_bool(row["feedback_converged"]),
        blocked_ac_count=int(row["blocked_ac_count"]),
        blocked_ac_detail_json=_opt_str(row["blocked_ac_detail_json"]),
        llm_call_count=int(row["llm_call_count"]),
        adversarial_findings_count=int(row["adversarial_findings_count"]),
        adversarial_tests_created=int(row["adversarial_tests_created"]),
        adversarial_hit_rate=_opt_float(row["adversarial_hit_rate"]),
        findings_fully_resolved=int(row["findings_fully_resolved"]),
        findings_partially_resolved=int(row["findings_partially_resolved"]),
        findings_not_resolved=int(row["findings_not_resolved"]),
        final_status=_opt_str(row["final_status"]),
        are_gate_passed=_opt_bool(row["are_gate_passed"]),
        are_total_requirements=_opt_int(row["are_total_requirements"]),
        are_covered_requirements=_opt_int(row["are_covered_requirements"]),
        files_changed=int(row["files_changed"]),
        increment_count=int(row["increment_count"]),
        phase_setup_ms=_opt_int(row["phase_setup_ms"]),
        phase_exploration_ms=_opt_int(row["phase_exploration_ms"]),
        phase_implementation_ms=_opt_int(row["phase_implementation_ms"]),
        phase_verify_ms=_opt_int(row["phase_verify_ms"]),
        phase_closure_ms=_opt_int(row["phase_closure_ms"]),
        computed_at=_require_dt(row["computed_at"], "fact_story.computed_at"),
    )


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _opt_bool(value: Any) -> bool | None:
    """Read a nullable boolean (BOOLEAN on Postgres, 0/1 INTEGER on SQLite)."""
    return None if value is None else bool(value)


def _row_to_fact_guard(row: dict[str, Any]) -> FactGuardPeriod:
    return FactGuardPeriod(
        project_key=str(row["project_key"]),
        guard_key=str(row["guard_key"]),
        period_start=_require_dt(row["period_start"], "fact_guard_period.period_start"),
        period_grain=str(row["period_grain"]),
        invocation_count=int(row["invocation_count"]),
        violation_count=int(row["violation_count"]),
        violation_rate=_opt_float(row["violation_rate"]),
        violation_stage_escape=int(row["violation_stage_escape"]),
        violation_stage_schema=int(row["violation_stage_schema"]),
        violation_stage_template=int(row["violation_stage_template"]),
        escape_detection_count=int(row["escape_detection_count"]),
        computed_at=_require_dt(row["computed_at"], "fact_guard_period.computed_at"),
    )


def _row_to_fact_pool(row: dict[str, Any]) -> FactPoolPeriod:
    return FactPoolPeriod(
        project_key=str(row["project_key"]),
        pool_key=str(row["pool_key"]),
        period_start=_require_dt(row["period_start"], "fact_pool_period.period_start"),
        period_grain=str(row["period_grain"]),
        call_count=int(row["call_count"]),
        response_time_p50_ms=_opt_int(row["response_time_p50_ms"]),
        verdict_adopted_count=int(row["verdict_adopted_count"]),
        verdict_total_count=int(row["verdict_total_count"]),
        finding_true_positive_count=int(row["finding_true_positive_count"]),
        finding_false_positive_count=int(row["finding_false_positive_count"]),
        quorum_triggered_count=int(row["quorum_triggered_count"]),
        template_finding_rate_json=_opt_str(row["template_finding_rate_json"]),
        computed_at=_require_dt(row["computed_at"], "fact_pool_period.computed_at"),
    )


def _row_to_fact_pipeline(row: dict[str, Any]) -> FactPipelinePeriod:
    return FactPipelinePeriod(
        project_key=str(row["project_key"]),
        period_start=_require_dt(
            row["period_start"], "fact_pipeline_period.period_start"
        ),
        period_grain=str(row["period_grain"]),
        story_count=int(row["story_count"]),
        story_count_closed=int(row["story_count_closed"]),
        execution_count=int(row["execution_count"]),
        exploration_count=int(row["exploration_count"]),
        stage_miss_count=int(row["stage_miss_count"]),
        stage_miss_detail_json=_opt_str(row["stage_miss_detail_json"]),
        impact_violation_count=int(row["impact_violation_count"]),
        impact_check_count=int(row["impact_check_count"]),
        integrity_gate_block_count=int(row["integrity_gate_block_count"]),
        integrity_gate_total_count=int(row["integrity_gate_total_count"]),
        doc_fidelity_conflict_by_level_json=_opt_str(
            row["doc_fidelity_conflict_by_level_json"]
        ),
        first_pass_count=int(row["first_pass_count"]),
        finding_survival_count=int(row["finding_survival_count"]),
        finding_total_count=int(row["finding_total_count"]),
        effective_check_ids_json=_opt_str(row["effective_check_ids_json"]),
        vectordb_total_hits=int(row["vectordb_total_hits"]),
        vectordb_above_threshold=int(row["vectordb_above_threshold"]),
        vectordb_classified_conflict=int(row["vectordb_classified_conflict"]),
        vectordb_duplicate_detected=int(row["vectordb_duplicate_detected"]),
        processing_time_avg_ms=_opt_int(row["processing_time_avg_ms"]),
        processing_time_variance_ms2=_opt_float(
            row["processing_time_variance_ms2"]
        ),
        qa_round_avg=_opt_float(row["qa_round_avg"]),
        computed_at=_require_dt(
            row["computed_at"], "fact_pipeline_period.computed_at"
        ),
    )


def _row_to_fact_corpus(row: dict[str, Any]) -> FactCorpusPeriod:
    return FactCorpusPeriod(
        project_key=str(row["project_key"]),
        period_start=_require_dt(row["period_start"], "fact_corpus_period.period_start"),
        period_grain=str(row["period_grain"]),
        new_incident_count=int(row["new_incident_count"]),
        patterns_total_count=int(row["patterns_total_count"]),
        patterns_with_active_check=int(row["patterns_with_active_check"]),
        computed_at=_require_dt(row["computed_at"], "fact_corpus_period.computed_at"),
    )


def _row_to_counter(row: dict[str, Any]) -> GuardInvocationCounter:
    return GuardInvocationCounter(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        guard_key=str(row["guard_key"]),
        week_start=str(row["week_start"]),
        invocations=int(row["invocations"]),
        blocks=int(row["blocks"]),
        updated_at=_require_dt(row["updated_at"], "guard_invocation_counters.updated_at"),
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
# SQL-fragment constants live in the sibling ``_fact_sql`` module so this
# adapter's module-level LOC stays within budget; re-imported under their
# original names (no behaviour change).


def _named(columns: str) -> str:
    """Turn ``a, b, c`` into the named-placeholder list ``:a, :b, :c``."""
    return ", ".join(f":{c.strip()}" for c in columns.split(","))


def _upsert_statement(
    *, table: str, columns: str, conflict: str, update_clause: str, is_postgres: bool
) -> str:
    """Build an idempotent INSERT ... ON CONFLICT DO UPDATE for the active backend."""
    placeholders = (
        ", ".join(f"%({c.strip()})s" for c in columns.split(","))
        if is_postgres
        else _named(columns)
    )
    return (
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict}) DO UPDATE SET {update_clause}"
    )


def _sync_state_params(state: SyncState, *, is_postgres: bool) -> dict[str, Any]:
    return {
        "project_key": state.project_key,
        "key": state.key,
        "value_int": state.value_int,
        "value_text": state.value_text,
        "updated_at": _ts(state.updated_at, is_postgres=is_postgres),
    }


class StateBackendFactRepository:
    """SQLite/Postgres implementation of ``FactRepository`` (AG3-038).

    Backend selected via ``AGENTKIT_STATE_BACKEND``; Postgres is canonical,
    SQLite is the test-parallel path (``AGENTKIT_ALLOW_SQLITE=1``).

    Args:
        store_dir: Base directory for the SQLite store (Postgres ignores it).
            When ``None`` and the SQLite backend is active, the root is resolved
            fail-closed from ``AGENTKIT_STORE_DIR`` (AG3-094 E9 — NO ``Path.cwd()``
            hidden state). Postgres never touches this value.

    Note:
        AG3-094 (E9 + jenkins-460 scope-correction): the implicit (no-arg) case
        resolves the SQLite root from ``AGENTKIT_STORE_DIR`` (fail-closed) because
        the REAL KPI read endpoint constructs this repository with NO ``store_dir``
        (``control_plane_http.app``) and the AG3-094 SSE E2E harness sets
        ``AGENTKIT_STORE_DIR`` (no ``os.chdir``) so the KPI seed (explicit dir) and
        read (implicit) share one store. This explicit-root resolution is kept; the
        narrowing of the broad fail-closed back out of UNRELATED pre-existing global
        reads happens in ``sqlite_store`` (story-context / phase-state /
        story-execution-lock) — see the AG3-094 jenkins-460 note.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._explicit_store_dir: Path | None = store_dir

    @property
    def _store_dir(self) -> Path:
        """Resolve the SQLite store root (explicit arg or configured root).

        AG3-094 (E9, FIX THE MODEL): the implicit (no-arg) case resolves from the
        EXPLICIT ``AGENTKIT_STORE_DIR`` root via the shared
        :func:`resolve_sqlite_store_root` — fail-closed — instead of defaulting to
        ``Path.cwd()``. Only ever consulted on the SQLite path; Postgres ignores
        the store dir entirely, so an unset root never breaks the Postgres backend.

        Raises:
            ConfigError: If no explicit dir was given AND ``AGENTKIT_STORE_DIR`` is
                unset (SQLite path only).
        """
        if self._explicit_store_dir is not None:
            return self._explicit_store_dir
        from agentkit.backend.state_backend.config import resolve_sqlite_store_root

        return Path(resolve_sqlite_store_root())

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def list_fact_stories(
        self, project_key: str, period: PeriodFilter | None = None
    ) -> list[FactStory]:
        """Return ``fact_story`` rows for ``project_key`` (period bounds closed_at)."""
        if period is None:
            query = (
                "SELECT * FROM fact_story WHERE project_key = ? "
                "ORDER BY story_id"
            )
            params: tuple[Any, ...] = (project_key,)
        else:
            query = (
                "SELECT * FROM fact_story WHERE project_key = ? "
                "AND closed_at >= ? AND closed_at < ? ORDER BY story_id"
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
            "ORDER BY guard_key, period_start"
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
            "ORDER BY pool_key, period_start"
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
            columns=_FACT_GUARD_COLUMNS,
            conflict=_FACT_GUARD_CONFLICT,
            update_clause=_FACT_GUARD_UPDATE,
            params=_fact_guard_params(fact, is_postgres=is_pg),
        )

    def upsert_fact_pool(self, fact: FactPoolPeriod) -> None:
        """Insert-or-replace one ``fact_pool_period`` row on its PK."""
        is_pg = _is_postgres()
        self._upsert(
            table="fact_pool_period",
            columns=_FACT_POOL_COLUMNS,
            conflict=_FACT_POOL_CONFLICT,
            update_clause=_FACT_POOL_UPDATE,
            params=_fact_pool_params(fact, is_postgres=is_pg),
        )

    def upsert_fact_pipeline(self, fact: FactPipelinePeriod) -> None:
        """Insert-or-replace one ``fact_pipeline_period`` row on its PK."""
        is_pg = _is_postgres()
        self._upsert(
            table="fact_pipeline_period",
            columns=_FACT_PIPELINE_COLUMNS,
            conflict=_FACT_PIPELINE_CONFLICT,
            update_clause=_FACT_PIPELINE_UPDATE,
            params=_fact_pipeline_params(fact, is_postgres=is_pg),
        )

    def upsert_fact_corpus(self, fact: FactCorpusPeriod) -> None:
        """Insert-or-replace one ``fact_corpus_period`` row on its PK."""
        is_pg = _is_postgres()
        self._upsert(
            table="fact_corpus_period",
            columns=_FACT_CORPUS_COLUMNS,
            conflict=_FACT_CORPUS_CONFLICT,
            update_clause=_FACT_CORPUS_UPDATE,
            params=_fact_corpus_params(fact, is_postgres=is_pg),
        )

    def upsert_sync_state(self, state: SyncState) -> None:
        """Insert-or-replace one ``sync_state`` cursor row on ``(project_key, key)``."""
        is_pg = _is_postgres()
        self._upsert(
            table="sync_state",
            columns=_SYNC_STATE_COLUMNS,
            conflict=_SYNC_STATE_CONFLICT,
            update_clause=_SYNC_STATE_UPDATE,
            params=_sync_state_params(state, is_postgres=is_pg),
        )

    # ------------------------------------------------------------------
    # atomic write session (FK-62 §62.3.2/§62.3.3)
    # ------------------------------------------------------------------

    @contextmanager
    def begin_write_session(self) -> Iterator[_FactWriteSession]:
        """Open ONE atomic transaction over the analytics tables (FK-62 §62.3.2).

        Holds a single connection for the whole RefreshWorker run; commits on
        clean exit, rolls back on any exception (no partial commit, FK-62
        §62.3.7). The guard-counter scratchpad lives in the SAME database file /
        instance as the fact tables, so its drain commits atomically with the
        ``fact_guard_period`` write (FK-62 §62.2.6).
        """
        is_pg = _is_postgres()
        if is_pg:
            with _postgres_connect() as conn:
                yield _FactWriteSession(conn, is_postgres=True)
            return
        with _sqlite_connect(self._store_dir) as conn:
            yield _FactWriteSession(conn, is_postgres=False)

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
        is_pg = _is_postgres()
        statement = _upsert_statement(
            table=table,
            columns=columns,
            conflict=conflict,
            update_clause=update_clause,
            is_postgres=is_pg,
        )
        if is_pg:
            with _postgres_connect() as conn:
                conn.execute(statement, params)
            return
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute(statement, params)


class _FactWriteSession:
    """One atomic transaction over the analytics tables (FK-62 §62.3.2/§62.3.3).

    Bound to the single connection opened by ``begin_write_session``. Statements
    run WITHOUT an intermediate commit; the surrounding context manager commits on
    clean exit and rolls back on any exception. The ``replace_<table>_period``
    ports DELETE every passed slice key and then INSERT the recomputed rows, so a
    slice that recomputes to no row ends up absent (FK-62 §62.2.8).
    """

    def __init__(self, conn: Any, *, is_postgres: bool) -> None:
        self._conn = conn
        self._is_pg = is_postgres

    # -- helpers ---------------------------------------------------------

    def _execute(self, statement: str, params: Any) -> Any:
        # Same call on both backends: the placeholder dialect is already baked into
        # ``statement`` before this point (``%s`` for Postgres, ``?``/``:name`` for
        # SQLite). The session holds the open connection so no commit happens here.
        return self._conn.execute(statement, params)

    def _delete_keys(
        self,
        table: str,
        key_columns: tuple[str, ...],
        keys: Sequence[tuple[Any, ...]],
    ) -> None:
        where = " AND ".join(f"{col} = ?" for col in key_columns)
        statement = f"DELETE FROM {table} WHERE {where}"
        if self._is_pg:
            statement = statement.replace("?", "%s")
        for key in self._slice_keys(keys):
            self._execute(statement, key)

    def _insert(
        self, *, table: str, columns: str, params: dict[str, Any]
    ) -> None:
        placeholders = (
            ", ".join(f"%({c.strip()})s" for c in columns.split(","))
            if self._is_pg
            else _named(columns)
        )
        statement = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        self._execute(statement, params)

    # -- fact_story ------------------------------------------------------

    def upsert_fact_story(self, fact: FactStory) -> None:
        """Insert-or-replace one ``fact_story`` row inside the open transaction."""
        statement = _upsert_statement(
            table="fact_story",
            columns=_FACT_STORY_COLUMNS,
            conflict="project_key, story_id",
            update_clause=_FACT_STORY_UPDATE,
            is_postgres=self._is_pg,
        )
        self._execute(statement, _fact_story_params(fact, is_postgres=self._is_pg))

    def delete_fact_story(self, project_key: str, story_id: str) -> int:
        """Delete the ``fact_story`` row of ``(project_key, story_id)``; return rows."""
        statement = (
            "DELETE FROM fact_story WHERE project_key = ? AND story_id = ?"
        )
        if self._is_pg:
            statement = statement.replace("?", "%s")
        cursor = self._execute(statement, (project_key, story_id))
        return int(cursor.rowcount)

    # -- period replaces (DELETE slice keys, then INSERT recomputed rows) -

    def replace_guard_period(
        self,
        keys: Sequence[tuple[str, str, datetime]],
        rows: list[FactGuardPeriod],
    ) -> None:
        """DELETE the guard-week slices, then INSERT the recomputed rows."""
        self._delete_keys(
            "fact_guard_period",
            ("project_key", "guard_key", "period_start"),
            keys,
        )
        for row in rows:
            self._insert(
                table="fact_guard_period",
                columns=_FACT_GUARD_COLUMNS,
                params=_fact_guard_params(row, is_postgres=self._is_pg),
            )

    def replace_pool_period(
        self,
        keys: Sequence[tuple[str, str, datetime]],
        rows: list[FactPoolPeriod],
    ) -> None:
        """DELETE the pool-week slices, then INSERT the recomputed rows."""
        self._delete_keys(
            "fact_pool_period",
            ("project_key", "pool_key", "period_start"),
            keys,
        )
        for row in rows:
            self._insert(
                table="fact_pool_period",
                columns=_FACT_POOL_COLUMNS,
                params=_fact_pool_params(row, is_postgres=self._is_pg),
            )

    def replace_pipeline_period(
        self,
        keys: Sequence[tuple[str, datetime]],
        rows: list[FactPipelinePeriod],
    ) -> None:
        """DELETE the pipeline-week slices, then INSERT the recomputed rows."""
        self._delete_keys(
            "fact_pipeline_period",
            ("project_key", "period_start"),
            keys,
        )
        for row in rows:
            self._insert(
                table="fact_pipeline_period",
                columns=_FACT_PIPELINE_COLUMNS,
                params=_fact_pipeline_params(row, is_postgres=self._is_pg),
            )

    def replace_corpus_period(
        self,
        keys: Sequence[tuple[str, datetime]],
        rows: list[FactCorpusPeriod],
    ) -> None:
        """DELETE the corpus-month slices, then INSERT the recomputed rows."""
        self._delete_keys(
            "fact_corpus_period",
            ("project_key", "period_start"),
            keys,
        )
        for row in rows:
            self._insert(
                table="fact_corpus_period",
                columns=_FACT_CORPUS_COLUMNS,
                params=_fact_corpus_params(row, is_postgres=self._is_pg),
            )

    def _slice_keys(
        self, keys: Sequence[tuple[Any, ...]]
    ) -> list[tuple[object, ...]]:
        """Bind the ``period_start`` (trailing ``datetime``) element of each key.

        A period slice key ends with the period-start ``datetime`` — the SAME
        value the recomputed row carries — so the DELETE matches the stored row
        exactly. ``_ts`` binds it per backend (native ``datetime`` on Postgres,
        ISO-8601 TEXT on SQLite, mirroring how the rows were written).
        """
        bound: list[tuple[object, ...]] = []
        for key in keys:
            *head, period_start = key
            bound.append((*head, _ts(period_start, is_postgres=self._is_pg)))
        return bound

    # -- cursor ----------------------------------------------------------

    def update_sync_cursor(self, state: SyncState) -> None:
        """Upsert the ``sync_state`` cursor row inside the open transaction."""
        statement = _upsert_statement(
            table="sync_state",
            columns=_SYNC_STATE_COLUMNS,
            conflict=_SYNC_STATE_CONFLICT,
            update_clause=_SYNC_STATE_UPDATE,
            is_postgres=self._is_pg,
        )
        self._execute(statement, _sync_state_params(state, is_postgres=self._is_pg))

    # -- guard-counter drain (same transaction, FK-62 §62.2.6) -----------

    def read_guard_counters_for_story(
        self, project_key: str, story_id: str
    ) -> list[GuardInvocationCounter]:
        """Read the story's ``guard_invocation_counters`` rows in-session."""
        statement = (
            "SELECT * FROM guard_invocation_counters WHERE project_key = ? "
            "AND story_id = ? ORDER BY guard_key, week_start"
        )
        if self._is_pg:
            statement = statement.replace("?", "%s")
        rows = self._execute(statement, (project_key, story_id)).fetchall()
        return [_row_to_counter(dict(r)) for r in rows]

    def delete_guard_counters_for_story(
        self, project_key: str, story_id: str
    ) -> int:
        """Delete the story's ``guard_invocation_counters`` rows in-session; return rows."""
        statement = (
            "DELETE FROM guard_invocation_counters WHERE project_key = ? "
            "AND story_id = ?"
        )
        if self._is_pg:
            statement = statement.replace("?", "%s")
        cursor = self._execute(statement, (project_key, story_id))
        return int(cursor.rowcount)


__all__ = ["StateBackendFactRepository"]
