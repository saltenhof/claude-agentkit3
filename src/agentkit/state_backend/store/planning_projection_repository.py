"""State-backend adapters for the ten BC14 planning projection tables (FK-70 §70.10.2).

DB-layer (BC9) implementations of the planning projection repository protocols.
Schema owner is BC14 (execution-planning); DB access is BC9. Each adapter
self-bootstraps its table (DDL) on connect -- idempotent ``CREATE IF NOT
EXISTS`` -- analogous to the FK-69 ``risk_window`` adapter, and supports both
SQLite (narrow unit/integration) and Postgres backends.

These adapters are owner-distinct from the FK-69 ``Facade*`` projection
repositories; they do NOT route through the FK-69 ``ProjectionAccessor``. They
are wired into ``PlanningProjectionRepositories`` in the composition root and
injected into ``PlanningProjectionAccessor`` (the single planning write path).

Sources:
- FK-70 §70.10.2 -- schema owner BC14, DB owner BC9, ten schema families
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.execution_planning.persistence.records import (
    BlockingConditionRecord,
    DependencyEdgeRecord,
    ExecutionPlanRecord,
    ExecutionWaveRecord,
    GateRecord,
    PlannedStoryRecord,
    RulebookCompileResultRecord,
    RulebookRevisionRecord,
    SchedulingBudgetRecord,
    SchedulingPolicyRecord,
)
from agentkit.execution_planning.persistence.repositories import (
    PlanningProjectionRepositories,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentkit.execution_planning.persistence.filter import PlanningProjectionFilter

__all__ = [
    "StateBackendBlockingConditionProjectionRepository",
    "StateBackendDependencyEdgeProjectionRepository",
    "StateBackendExecutionPlanProjectionRepository",
    "StateBackendExecutionWaveProjectionRepository",
    "StateBackendGateProjectionRepository",
    "StateBackendPlannedStoryProjectionRepository",
    "StateBackendRulebookCompileResultProjectionRepository",
    "StateBackendRulebookRevisionProjectionRepository",
    "StateBackendSchedulingBudgetProjectionRepository",
    "StateBackendSchedulingPolicyProjectionRepository",
    "build_planning_projection_repositories",
]


# ---------------------------------------------------------------------------
# DDL for the ten planning tables (BC14 schema owner) -- SQLite + Postgres.
# ---------------------------------------------------------------------------

_PLANNING_DDL_SQLITE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS planning_planned_story (
        project_key TEXT NOT NULL,
        story_id TEXT NOT NULL,
        story_type TEXT NOT NULL,
        story_size TEXT NOT NULL,
        participating_repos_json TEXT NOT NULL,
        planning_status TEXT NOT NULL,
        is_hard_truth INTEGER NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, story_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_dependency_edge (
        project_key TEXT NOT NULL,
        story_id TEXT NOT NULL,
        depends_on_story_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        rationale TEXT,
        is_hard_truth INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, story_id, depends_on_story_id, kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_blocking_condition (
        project_key TEXT NOT NULL,
        blocker_id TEXT NOT NULL,
        story_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        provenance TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        source_story_id TEXT,
        source_gate_id TEXT,
        detail TEXT,
        is_hard_truth INTEGER NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, blocker_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_gate (
        project_key TEXT NOT NULL,
        gate_id TEXT NOT NULL,
        story_id TEXT NOT NULL,
        gate_kind TEXT NOT NULL,
        state TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        is_blocking INTEGER NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, gate_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_scheduling_budget (
        project_key TEXT NOT NULL,
        budget_id TEXT NOT NULL,
        repo_parallel_cap INTEGER NOT NULL,
        merge_risk_cap INTEGER NOT NULL,
        api_rate_limit_cap INTEGER NOT NULL,
        llm_pool_cap INTEGER NOT NULL,
        ci_capacity_cap INTEGER NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, budget_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_scheduling_policy (
        project_key TEXT NOT NULL,
        policy_id TEXT NOT NULL,
        may_parallelize_now INTEGER NOT NULL,
        budget_id TEXT NOT NULL,
        recommended_batch_limit INTEGER,
        reason_code TEXT NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, policy_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_rulebook_revision (
        project_key TEXT NOT NULL,
        rulebook_id TEXT NOT NULL,
        revision INTEGER NOT NULL,
        raw_syntax TEXT NOT NULL,
        updated_by_principal TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (project_key, rulebook_id, revision)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_rulebook_compile_result (
        project_key TEXT NOT NULL,
        rulebook_id TEXT NOT NULL,
        revision INTEGER NOT NULL,
        status TEXT NOT NULL,
        compiled_rules_json TEXT NOT NULL,
        errors_json TEXT NOT NULL,
        triggers_replan INTEGER NOT NULL,
        compiled_at TEXT NOT NULL,
        PRIMARY KEY (project_key, rulebook_id, revision)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_execution_plan (
        project_key TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        graph_revision INTEGER NOT NULL,
        readiness_revision INTEGER NOT NULL,
        scheduling_revision INTEGER NOT NULL,
        rulebook_revision INTEGER NOT NULL,
        critical_path_json TEXT NOT NULL,
        recommended_batch_json TEXT NOT NULL,
        max_allowed_batch_json TEXT NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, plan_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_execution_wave (
        project_key TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        wave_id TEXT NOT NULL,
        wave_order INTEGER NOT NULL,
        wave_state TEXT NOT NULL,
        candidate_story_ids_json TEXT NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, plan_id, wave_id)
    )
    """,
)

# Postgres DDL: same shape, INTEGER->BOOLEAN for the flag columns is unnecessary
# (we store 0/1 ints there too for symmetry with the record bool<->int mapping).
_PLANNING_DDL_POSTGRES: tuple[str, ...] = _PLANNING_DDL_SQLITE


def _is_postgres() -> bool:
    from agentkit.state_backend.config import StateBackendKind, load_state_backend_config

    return load_state_backend_config().backend is StateBackendKind.POSTGRES


def _sqlite_db_path(store_dir: Path) -> Path:
    from agentkit.state_backend.config import versioned_sqlite_db_file
    from agentkit.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    from agentkit.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed

    if not _sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for this path. "
            f"Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution."
        )
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    current_mode = conn.execute("PRAGMA journal_mode").fetchone()
    if current_mode is None or str(current_mode[0]).lower() != "wal":
        conn.execute("PRAGMA journal_mode=WAL")
    for statement in _PLANNING_DDL_SQLITE:
        conn.execute(statement)
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
    import os

    import psycopg
    from psycopg.rows import dict_row

    url = os.environ.get("AGENTKIT_STATE_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "AGENTKIT_STATE_DATABASE_URL must be set when "
            "AGENTKIT_STATE_BACKEND=postgres"
        )
    conn = psycopg.connect(url, row_factory=dict_row)
    try:
        for statement in _PLANNING_DDL_POSTGRES:
            conn.execute(statement)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class _PlanningTableAdapter:
    """Shared SQLite/Postgres upsert+select machinery for one planning table.

    Subclasses declare the table name, the primary-key columns and the
    record<->row mapping. The base handles connection selection, DDL bootstrap,
    deterministic upsert (idempotency / revision binding per FK-70 §70.11 #8) and
    project-scoped filtered reads.

    Args:
        store_dir: Base directory for the SQLite store (Postgres ignores it).
    """

    _table: str
    _pk_columns: tuple[str, ...]

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    def _row_from_record(self, record: Any) -> dict[str, Any]:  # noqa: ANN401
        raise NotImplementedError

    def _record_from_row(self, row: dict[str, Any]) -> Any:  # noqa: ANN401
        raise NotImplementedError

    def _upsert(self, row: dict[str, Any]) -> None:
        columns = list(row.keys())
        if _is_postgres():
            placeholders = ", ".join(f"%({col})s" for col in columns)
            update_cols = [c for c in columns if c not in self._pk_columns]
            set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
            conflict = ", ".join(self._pk_columns)
            sql = (
                f"INSERT INTO {self._table} ({', '.join(columns)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict}) DO UPDATE SET {set_clause}"
            )
            with _postgres_connect() as conn:
                conn.execute(sql, row)
        else:
            placeholders = ", ".join(f":{col}" for col in columns)
            sql = (
                f"INSERT OR REPLACE INTO {self._table} ({', '.join(columns)}) "
                f"VALUES ({placeholders})"
            )
            with _sqlite_connect(self._store_dir) as conn:
                conn.execute(sql, row)

    def _select(self, filter: PlanningProjectionFilter) -> list[Any]:  # noqa: A002
        clauses: list[str] = []
        params: dict[str, Any] = {}
        # project_key is mandant-mandatory at the read boundary (FAIL-CLOSED).
        clauses.append("project_key = :project_key")
        params["project_key"] = filter.project_key
        for column, value in (
            ("story_id", filter.story_id),
            ("plan_id", filter.plan_id),
            ("rulebook_id", filter.rulebook_id),
            ("revision", filter.revision),
        ):
            if value is not None and self._has_column(column):
                clauses.append(f"{column} = :{column}")
                params[column] = value
        where = " AND ".join(clauses)
        sql = f"SELECT * FROM {self._table} WHERE {where}"
        if _is_postgres():
            pg_sql = sql
            for key in params:
                pg_sql = pg_sql.replace(f":{key}", f"%({key})s")
            with _postgres_connect() as conn:
                rows = conn.execute(pg_sql, params).fetchall()
            return [self._record_from_row(dict(r)) for r in rows]
        with _sqlite_connect(self._store_dir) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._record_from_row(dict(r)) for r in rows]

    def _has_column(self, column: str) -> bool:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Concrete adapters
# ---------------------------------------------------------------------------


def _loads(value: Any) -> tuple[str, ...]:  # noqa: ANN401
    return tuple(json.loads(value)) if value else ()


class StateBackendPlannedStoryProjectionRepository(_PlanningTableAdapter):
    """Adapter for ``planned_story``."""

    _table = "planning_planned_story"
    _pk_columns = ("project_key", "story_id")

    def _has_column(self, column: str) -> bool:
        return column in {"story_id", "revision"}

    def _row_from_record(self, record: PlannedStoryRecord) -> dict[str, Any]:
        return {
            "project_key": record.project_key,
            "story_id": record.story_id,
            "story_type": record.story_type,
            "story_size": record.story_size,
            "participating_repos_json": json.dumps(list(record.participating_repos)),
            "planning_status": record.planning_status,
            "is_hard_truth": 1 if record.is_hard_truth else 0,
            "revision": record.revision,
        }

    def _record_from_row(self, row: dict[str, Any]) -> PlannedStoryRecord:
        return PlannedStoryRecord(
            project_key=str(row["project_key"]),
            story_id=str(row["story_id"]),
            story_type=str(row["story_type"]),
            story_size=str(row["story_size"]),
            participating_repos=_loads(row["participating_repos_json"]),
            planning_status=str(row["planning_status"]),
            is_hard_truth=bool(row["is_hard_truth"]),
            revision=int(row["revision"]),
        )

    def write(self, record: PlannedStoryRecord) -> None:
        self._upsert(self._row_from_record(record))

    def read(self, filter: PlanningProjectionFilter) -> list[PlannedStoryRecord]:  # noqa: A002
        return list(self._select(filter))


class StateBackendDependencyEdgeProjectionRepository(_PlanningTableAdapter):
    """Adapter for ``dependency_edge`` (migrated planning write path)."""

    _table = "planning_dependency_edge"
    _pk_columns = ("project_key", "story_id", "depends_on_story_id", "kind")

    def _has_column(self, column: str) -> bool:
        return column in {"story_id", "revision"}

    def _row_from_record(self, record: DependencyEdgeRecord) -> dict[str, Any]:
        return {
            "project_key": record.project_key,
            "story_id": record.story_id,
            "depends_on_story_id": record.depends_on_story_id,
            "kind": record.kind,
            "rationale": record.rationale,
            "is_hard_truth": 1 if record.is_hard_truth else 0,
            "created_at": record.created_at,
            "revision": record.revision,
        }

    def _record_from_row(self, row: dict[str, Any]) -> DependencyEdgeRecord:
        return DependencyEdgeRecord(
            project_key=str(row["project_key"]),
            story_id=str(row["story_id"]),
            depends_on_story_id=str(row["depends_on_story_id"]),
            kind=str(row["kind"]),
            rationale=str(row["rationale"]) if row["rationale"] is not None else None,
            is_hard_truth=bool(row["is_hard_truth"]),
            created_at=str(row["created_at"]),
            revision=int(row["revision"]),
        )

    def write(self, record: DependencyEdgeRecord) -> None:
        self._upsert(self._row_from_record(record))

    def read(self, filter: PlanningProjectionFilter) -> list[DependencyEdgeRecord]:  # noqa: A002
        return list(self._select(filter))

    def read_for_story(self, story_id: str) -> list[DependencyEdgeRecord]:
        """Read all dependency edges for one story across the store (no project filter).

        Supports the migrated ``StoryDependencyRepository.list_for_story``, whose
        port carries only a ``story_id``. Story display ids are globally unique
        in practice; mandant isolation at the read boundary is preserved by the
        primary ``read``/``write`` paths which require ``project_key``.
        """
        if _is_postgres():
            with _postgres_connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM {self._table} WHERE story_id = %(story_id)s",
                    {"story_id": story_id},
                ).fetchall()
            return [self._record_from_row(dict(r)) for r in rows]
        with _sqlite_connect(self._store_dir) as conn:
            rows = conn.execute(
                f"SELECT * FROM {self._table} WHERE story_id = :story_id",
                {"story_id": story_id},
            ).fetchall()
        return [self._record_from_row(dict(r)) for r in rows]

    def delete(
        self,
        *,
        project_key: str,
        story_id: str,
        depends_on_story_id: str,
        kind: str,
    ) -> int:
        """Delete one dependency edge by composite identity; return rows removed."""
        params = {
            "project_key": project_key,
            "story_id": story_id,
            "depends_on_story_id": depends_on_story_id,
            "kind": kind,
        }
        where = (
            "project_key = :project_key AND story_id = :story_id "
            "AND depends_on_story_id = :depends_on_story_id AND kind = :kind"
        )
        if _is_postgres():
            pg_where = where
            for key in params:
                pg_where = pg_where.replace(f":{key}", f"%({key})s")
            with _postgres_connect() as conn:
                cursor = conn.execute(
                    f"DELETE FROM {self._table} WHERE {pg_where}", params
                )
                return int(cursor.rowcount)
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(f"DELETE FROM {self._table} WHERE {where}", params)
            return int(cursor.rowcount)


class StateBackendBlockingConditionProjectionRepository(_PlanningTableAdapter):
    """Adapter for ``blocking_condition``."""

    _table = "planning_blocking_condition"
    _pk_columns = ("project_key", "blocker_id")

    def _has_column(self, column: str) -> bool:
        return column in {"story_id", "revision"}

    def _row_from_record(self, record: BlockingConditionRecord) -> dict[str, Any]:
        return {
            "project_key": record.project_key,
            "blocker_id": record.blocker_id,
            "story_id": record.story_id,
            "kind": record.kind,
            "provenance": record.provenance,
            "reason_code": record.reason_code,
            "source_story_id": record.source_story_id,
            "source_gate_id": record.source_gate_id,
            "detail": record.detail,
            "is_hard_truth": 1 if record.is_hard_truth else 0,
            "revision": record.revision,
        }

    def _record_from_row(self, row: dict[str, Any]) -> BlockingConditionRecord:
        return BlockingConditionRecord(
            project_key=str(row["project_key"]),
            blocker_id=str(row["blocker_id"]),
            story_id=str(row["story_id"]),
            kind=str(row["kind"]),
            provenance=str(row["provenance"]),
            reason_code=str(row["reason_code"]),
            source_story_id=(
                str(row["source_story_id"]) if row["source_story_id"] is not None else None
            ),
            source_gate_id=(
                str(row["source_gate_id"]) if row["source_gate_id"] is not None else None
            ),
            detail=str(row["detail"]) if row["detail"] is not None else None,
            is_hard_truth=bool(row["is_hard_truth"]),
            revision=int(row["revision"]),
        )

    def write(self, record: BlockingConditionRecord) -> None:
        self._upsert(self._row_from_record(record))

    def read(self, filter: PlanningProjectionFilter) -> list[BlockingConditionRecord]:  # noqa: A002
        return list(self._select(filter))


class StateBackendGateProjectionRepository(_PlanningTableAdapter):
    """Adapter for ``gate``."""

    _table = "planning_gate"
    _pk_columns = ("project_key", "gate_id")

    def _has_column(self, column: str) -> bool:
        return column in {"story_id", "revision"}

    def _row_from_record(self, record: GateRecord) -> dict[str, Any]:
        return {
            "project_key": record.project_key,
            "gate_id": record.gate_id,
            "story_id": record.story_id,
            "gate_kind": record.gate_kind,
            "state": record.state,
            "reason_code": record.reason_code,
            "is_blocking": 1 if record.is_blocking else 0,
            "revision": record.revision,
        }

    def _record_from_row(self, row: dict[str, Any]) -> GateRecord:
        return GateRecord(
            project_key=str(row["project_key"]),
            gate_id=str(row["gate_id"]),
            story_id=str(row["story_id"]),
            gate_kind=str(row["gate_kind"]),
            state=str(row["state"]),
            reason_code=str(row["reason_code"]),
            is_blocking=bool(row["is_blocking"]),
            revision=int(row["revision"]),
        )

    def write(self, record: GateRecord) -> None:
        self._upsert(self._row_from_record(record))

    def read(self, filter: PlanningProjectionFilter) -> list[GateRecord]:  # noqa: A002
        return list(self._select(filter))


class StateBackendSchedulingBudgetProjectionRepository(_PlanningTableAdapter):
    """Adapter for ``scheduling_budget``."""

    _table = "planning_scheduling_budget"
    _pk_columns = ("project_key", "budget_id")

    def _has_column(self, column: str) -> bool:
        return column in {"revision"}

    def _row_from_record(self, record: SchedulingBudgetRecord) -> dict[str, Any]:
        return {
            "project_key": record.project_key,
            "budget_id": record.budget_id,
            "repo_parallel_cap": record.repo_parallel_cap,
            "merge_risk_cap": record.merge_risk_cap,
            "api_rate_limit_cap": record.api_rate_limit_cap,
            "llm_pool_cap": record.llm_pool_cap,
            "ci_capacity_cap": record.ci_capacity_cap,
            "revision": record.revision,
        }

    def _record_from_row(self, row: dict[str, Any]) -> SchedulingBudgetRecord:
        return SchedulingBudgetRecord(
            project_key=str(row["project_key"]),
            budget_id=str(row["budget_id"]),
            repo_parallel_cap=int(row["repo_parallel_cap"]),
            merge_risk_cap=int(row["merge_risk_cap"]),
            api_rate_limit_cap=int(row["api_rate_limit_cap"]),
            llm_pool_cap=int(row["llm_pool_cap"]),
            ci_capacity_cap=int(row["ci_capacity_cap"]),
            revision=int(row["revision"]),
        )

    def write(self, record: SchedulingBudgetRecord) -> None:
        self._upsert(self._row_from_record(record))

    def read(self, filter: PlanningProjectionFilter) -> list[SchedulingBudgetRecord]:  # noqa: A002
        return list(self._select(filter))


class StateBackendSchedulingPolicyProjectionRepository(_PlanningTableAdapter):
    """Adapter for ``scheduling_policy``."""

    _table = "planning_scheduling_policy"
    _pk_columns = ("project_key", "policy_id")

    def _has_column(self, column: str) -> bool:
        return column in {"revision"}

    def _row_from_record(self, record: SchedulingPolicyRecord) -> dict[str, Any]:
        return {
            "project_key": record.project_key,
            "policy_id": record.policy_id,
            "may_parallelize_now": 1 if record.may_parallelize_now else 0,
            "budget_id": record.budget_id,
            "recommended_batch_limit": record.recommended_batch_limit,
            "reason_code": record.reason_code,
            "revision": record.revision,
        }

    def _record_from_row(self, row: dict[str, Any]) -> SchedulingPolicyRecord:
        return SchedulingPolicyRecord(
            project_key=str(row["project_key"]),
            policy_id=str(row["policy_id"]),
            may_parallelize_now=bool(row["may_parallelize_now"]),
            budget_id=str(row["budget_id"]),
            recommended_batch_limit=(
                int(row["recommended_batch_limit"])
                if row["recommended_batch_limit"] is not None
                else None
            ),
            reason_code=str(row["reason_code"]),
            revision=int(row["revision"]),
        )

    def write(self, record: SchedulingPolicyRecord) -> None:
        self._upsert(self._row_from_record(record))

    def read(self, filter: PlanningProjectionFilter) -> list[SchedulingPolicyRecord]:  # noqa: A002
        return list(self._select(filter))


class StateBackendRulebookRevisionProjectionRepository(_PlanningTableAdapter):
    """Adapter for ``rulebook_revision``."""

    _table = "planning_rulebook_revision"
    _pk_columns = ("project_key", "rulebook_id", "revision")

    def _has_column(self, column: str) -> bool:
        return column in {"rulebook_id", "revision"}

    def _row_from_record(self, record: RulebookRevisionRecord) -> dict[str, Any]:
        return {
            "project_key": record.project_key,
            "rulebook_id": record.rulebook_id,
            "revision": record.revision,
            "raw_syntax": record.raw_syntax,
            "updated_by_principal": record.updated_by_principal,
            "created_at": record.created_at,
        }

    def _record_from_row(self, row: dict[str, Any]) -> RulebookRevisionRecord:
        return RulebookRevisionRecord(
            project_key=str(row["project_key"]),
            rulebook_id=str(row["rulebook_id"]),
            revision=int(row["revision"]),
            raw_syntax=str(row["raw_syntax"]),
            updated_by_principal=str(row["updated_by_principal"]),
            created_at=str(row["created_at"]),
        )

    def write(self, record: RulebookRevisionRecord) -> None:
        self._upsert(self._row_from_record(record))

    def read(self, filter: PlanningProjectionFilter) -> list[RulebookRevisionRecord]:  # noqa: A002
        return list(self._select(filter))


class StateBackendRulebookCompileResultProjectionRepository(_PlanningTableAdapter):
    """Adapter for ``rulebook_compile_result``."""

    _table = "planning_rulebook_compile_result"
    _pk_columns = ("project_key", "rulebook_id", "revision")

    def _has_column(self, column: str) -> bool:
        return column in {"rulebook_id", "revision"}

    def _row_from_record(self, record: RulebookCompileResultRecord) -> dict[str, Any]:
        return {
            "project_key": record.project_key,
            "rulebook_id": record.rulebook_id,
            "revision": record.revision,
            "status": record.status,
            "compiled_rules_json": record.compiled_rules_json,
            "errors_json": record.errors_json,
            "triggers_replan": 1 if record.triggers_replan else 0,
            "compiled_at": record.compiled_at,
        }

    def _record_from_row(self, row: dict[str, Any]) -> RulebookCompileResultRecord:
        return RulebookCompileResultRecord(
            project_key=str(row["project_key"]),
            rulebook_id=str(row["rulebook_id"]),
            revision=int(row["revision"]),
            status=str(row["status"]),
            compiled_rules_json=str(row["compiled_rules_json"]),
            errors_json=str(row["errors_json"]),
            triggers_replan=bool(row["triggers_replan"]),
            compiled_at=str(row["compiled_at"]),
        )

    def write(self, record: RulebookCompileResultRecord) -> None:
        self._upsert(self._row_from_record(record))

    def read(
        self,
        filter: PlanningProjectionFilter,  # noqa: A002
    ) -> list[RulebookCompileResultRecord]:
        return list(self._select(filter))


class StateBackendExecutionPlanProjectionRepository(_PlanningTableAdapter):
    """Adapter for ``execution_plan``."""

    _table = "planning_execution_plan"
    _pk_columns = ("project_key", "plan_id")

    def _has_column(self, column: str) -> bool:
        return column in {"plan_id", "revision"}

    def _row_from_record(self, record: ExecutionPlanRecord) -> dict[str, Any]:
        return {
            "project_key": record.project_key,
            "plan_id": record.plan_id,
            "graph_revision": record.graph_revision,
            "readiness_revision": record.readiness_revision,
            "scheduling_revision": record.scheduling_revision,
            "rulebook_revision": record.rulebook_revision,
            "critical_path_json": json.dumps(list(record.critical_path_story_ids)),
            "recommended_batch_json": json.dumps(
                list(record.recommended_batch_story_ids)
            ),
            "max_allowed_batch_json": json.dumps(
                list(record.max_allowed_batch_story_ids)
            ),
            "revision": record.revision,
        }

    def _record_from_row(self, row: dict[str, Any]) -> ExecutionPlanRecord:
        return ExecutionPlanRecord(
            project_key=str(row["project_key"]),
            plan_id=str(row["plan_id"]),
            graph_revision=int(row["graph_revision"]),
            readiness_revision=int(row["readiness_revision"]),
            scheduling_revision=int(row["scheduling_revision"]),
            rulebook_revision=int(row["rulebook_revision"]),
            critical_path_story_ids=_loads(row["critical_path_json"]),
            recommended_batch_story_ids=_loads(row["recommended_batch_json"]),
            max_allowed_batch_story_ids=_loads(row["max_allowed_batch_json"]),
            revision=int(row["revision"]),
        )

    def write(self, record: ExecutionPlanRecord) -> None:
        self._upsert(self._row_from_record(record))

    def read(self, filter: PlanningProjectionFilter) -> list[ExecutionPlanRecord]:  # noqa: A002
        return list(self._select(filter))


class StateBackendExecutionWaveProjectionRepository(_PlanningTableAdapter):
    """Adapter for ``execution_wave``."""

    _table = "planning_execution_wave"
    _pk_columns = ("project_key", "plan_id", "wave_id")

    def _has_column(self, column: str) -> bool:
        return column in {"plan_id", "revision"}

    def _row_from_record(self, record: ExecutionWaveRecord) -> dict[str, Any]:
        return {
            "project_key": record.project_key,
            "plan_id": record.plan_id,
            "wave_id": record.wave_id,
            "wave_order": record.wave_order,
            "wave_state": record.wave_state,
            "candidate_story_ids_json": json.dumps(list(record.candidate_story_ids)),
            "revision": record.revision,
        }

    def _record_from_row(self, row: dict[str, Any]) -> ExecutionWaveRecord:
        return ExecutionWaveRecord(
            project_key=str(row["project_key"]),
            plan_id=str(row["plan_id"]),
            wave_id=str(row["wave_id"]),
            wave_order=int(row["wave_order"]),
            wave_state=str(row["wave_state"]),
            candidate_story_ids=_loads(row["candidate_story_ids_json"]),
            revision=int(row["revision"]),
        )

    def write(self, record: ExecutionWaveRecord) -> None:
        self._upsert(self._row_from_record(record))

    def read(self, filter: PlanningProjectionFilter) -> list[ExecutionWaveRecord]:  # noqa: A002
        return list(self._select(filter))


def build_planning_projection_repositories(
    store_dir: Path | None = None,
) -> PlanningProjectionRepositories:
    """Build a fully wired ``PlanningProjectionRepositories`` instance.

    Composition-root helper, used by
    ``agentkit.bootstrap.composition_root.build_planning_projection_accessor``.

    Args:
        store_dir: State-backend base directory (SQLite only; Postgres ignores).

    Returns:
        A bundle of all ten concrete planning projection adapters.
    """

    return PlanningProjectionRepositories(
        planned_story=StateBackendPlannedStoryProjectionRepository(store_dir),
        dependency_edge=StateBackendDependencyEdgeProjectionRepository(store_dir),
        blocking_condition=StateBackendBlockingConditionProjectionRepository(store_dir),
        gate=StateBackendGateProjectionRepository(store_dir),
        scheduling_budget=StateBackendSchedulingBudgetProjectionRepository(store_dir),
        scheduling_policy=StateBackendSchedulingPolicyProjectionRepository(store_dir),
        rulebook_revision=StateBackendRulebookRevisionProjectionRepository(store_dir),
        rulebook_compile_result=(
            StateBackendRulebookCompileResultProjectionRepository(store_dir)
        ),
        execution_plan=StateBackendExecutionPlanProjectionRepository(store_dir),
        execution_wave=StateBackendExecutionWaveProjectionRepository(store_dir),
    )
