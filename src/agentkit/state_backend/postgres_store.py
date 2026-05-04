"""PostgreSQL-backed canonical runtime store with JSON projections.

This module is a T-bloodtype infrastructure driver.
It MUST NOT import BC-Records (A-bloodtype components).
All BC-Record <-> dict conversions live in
``agentkit.state_backend.store.mappers`` (boundary.state_backend_repository).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import psycopg
from psycopg.rows import dict_row

from agentkit.boundary.filesystem import atomic_write_json, load_json_object
from agentkit.boundary.shared.time import now_iso
from agentkit.exceptions import CorruptStateError
from agentkit.state_backend.config import (
    STATE_DATABASE_URL_ENV,
    load_state_backend_config,
)
from agentkit.state_backend.paths import (
    CLOSURE_REPORT_FILE,
    CONTEXT_EXPORT_FILE,
    PHASE_STATE_EXPORT_FILE,
    VERIFY_DECISION_FILE,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentkit.state_backend.scope import RuntimeStateScope


_PROJECT_KEY_FILTER = "project_key = ?"
_STORY_ID_FILTER = "story_id = ?"
_RUN_ID_FILTER = "run_id = ?"
_JsonRecord = dict[str, object]
_OptionalString = str | None


def _database_url() -> str:
    config = load_state_backend_config()
    if not config.database_url:
        raise RuntimeError(
            f"{STATE_DATABASE_URL_ENV} must be set when "
            "AGENTKIT_STATE_BACKEND=postgres",
        )
    return config.database_url


def _database_label() -> str:
    return STATE_DATABASE_URL_ENV


class _CompatConnection:
    """Compatibility wrapper translating sqlite-style queries to psycopg."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> psycopg.Cursor[dict[str, Any]]:
        normalized = query.replace("?", "%s")
        return self._conn.execute(normalized, params)

    def executescript(self, script: str) -> None:
        statements = [stmt.strip() for stmt in script.split(";") if stmt.strip()]
        for statement in statements:
            self._conn.execute(statement)


def load_json_safe(path: Path) -> _JsonRecord | None:
    """Compatibility helper for non-canonical export reads."""

    return load_json_object(path)


def _write_projection(path: Path, payload: _JsonRecord) -> None:
    """Atomically write a JSON projection file, creating parent dirs as needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


def _dump_json(data: object) -> str:
    return json.dumps(data, sort_keys=True, default=str)


def _load_json(data: str | None, default: Any) -> Any:
    if data is None:
        return default
    return json.loads(data)


def _cast_json_record(value: object) -> _JsonRecord:
    return cast("_JsonRecord", value)


def _cast_optional_str(value: object) -> _OptionalString:
    return cast("_OptionalString", value)


@contextmanager
def _connect_global() -> Iterator[_CompatConnection]:
    conn = psycopg.connect(
        _database_url(),
        row_factory=dict_row,
    )
    compat = _CompatConnection(conn)
    _ensure_schema(compat)
    try:
        yield compat
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _connect(story_dir: Path) -> Iterator[_CompatConnection]:
    del story_dir
    with _connect_global() as compat:
        yield compat


def _schema_create_script() -> str:
    schema_path = Path(__file__).with_name("postgres_schema.sql")
    return schema_path.read_text(encoding="utf-8")


def _schema_alter_statements() -> tuple[str, ...]:
    return (
        "CREATE EXTENSION IF NOT EXISTS pgcrypto",
        "ALTER TABLE story_contexts ADD COLUMN IF NOT EXISTS story_uuid UUID",
        "ALTER TABLE story_contexts ADD COLUMN IF NOT EXISTS story_number INTEGER",
        (
            "UPDATE story_contexts SET story_uuid = gen_random_uuid() "
            "WHERE story_uuid IS NULL"
        ),
        (
            "UPDATE story_contexts SET story_number = "
            "substring(story_id from '-([0-9]+)$')::INTEGER "
            "WHERE story_number IS NULL AND story_id ~ '-[0-9]+$'"
        ),
        (
            "INSERT INTO projects (key, name, story_id_prefix, configuration, "
            "archived_at) "
            "SELECT DISTINCT sc.project_key, sc.project_key, "
            "CASE WHEN EXISTS ("
            "SELECT 1 FROM projects p2 "
            "WHERE p2.story_id_prefix = split_part(sc.story_id, '-', 1) "
            "AND p2.key <> sc.project_key"
            ") THEN left(split_part(sc.story_id, '-', 1), 4) || "
            "upper(substr(md5(sc.project_key), 1, 6)) "
            "ELSE split_part(sc.story_id, '-', 1) END, "
            "'{\"repo_url\":\"\",\"default_branch\":\"main\",\"are_url\":null,"
            "\"default_worker_count\":1}'::jsonb, NULL::TIMESTAMPTZ "
            "FROM story_contexts sc "
            "LEFT JOIN projects p ON p.key = sc.project_key "
            "WHERE p.key IS NULL "
            "ON CONFLICT(key) DO NOTHING"
        ),
        "ALTER TABLE story_contexts ALTER COLUMN story_uuid SET DEFAULT gen_random_uuid()",
        "ALTER TABLE story_contexts ALTER COLUMN story_uuid SET NOT NULL",
        "ALTER TABLE story_contexts ALTER COLUMN story_number SET NOT NULL",
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_story_uuid_idx "
            "ON story_contexts (story_uuid)"
        ),
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_project_story_number_idx "
            "ON story_contexts (project_key, story_number)"
        ),
        (
            "INSERT INTO story_number_counters (project_key, next_story_number) "
            "SELECT project_key, COALESCE(MAX(story_number), 0) + 1 "
            "FROM story_contexts GROUP BY project_key "
            "ON CONFLICT(project_key) DO UPDATE SET next_story_number = "
            "GREATEST(story_number_counters.next_story_number, "
            "excluded.next_story_number)"
        ),
        (
            "ALTER TABLE story_execution_locks "
            "DROP CONSTRAINT IF EXISTS story_execution_locks_pkey"
        ),
        (
            "ALTER TABLE story_execution_locks "
            "ADD CONSTRAINT story_execution_locks_pkey "
            "PRIMARY KEY (project_key, run_id, lock_type)"
        ),
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS project_key TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS run_id TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS artifact_id TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS artifact_class TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS artifact_format TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS artifact_status TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS produced_in_phase TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS producer_component TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS producer_trust TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS protection_level TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS frozen INTEGER",
        (
            "ALTER TABLE artifact_records "
            "ADD COLUMN IF NOT EXISTS integrity_verified INTEGER"
        ),
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS attempt_no INTEGER",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS qa_cycle_id TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS qa_cycle_round INTEGER",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS evidence_epoch INTEGER",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS finished_at TEXT",
        "ALTER TABLE artifact_records ADD COLUMN IF NOT EXISTS storage_ref TEXT",
        "ALTER TABLE decision_records ADD COLUMN IF NOT EXISTS project_key TEXT",
        "ALTER TABLE decision_records ADD COLUMN IF NOT EXISTS run_id TEXT",
        "ALTER TABLE decision_records ADD COLUMN IF NOT EXISTS flow_id TEXT",
        "UPDATE phase_states SET phase = 'implementation' WHERE phase = 'verify'",
        (
            "UPDATE flow_executions SET current_node_id = 'implementation' "
            "WHERE current_node_id = 'verify'"
        ),
        (
            "UPDATE node_execution_ledgers n SET node_id = 'implementation' "
            "WHERE n.node_id = 'verify' AND NOT EXISTS ("
            "SELECT 1 FROM node_execution_ledgers existing "
            "WHERE existing.story_id = n.story_id "
            "AND existing.flow_id = n.flow_id "
            "AND existing.node_id = 'implementation')"
        ),
        "DELETE FROM node_execution_ledgers WHERE node_id = 'verify'",
        (
            "UPDATE phase_snapshots p SET phase = 'implementation' "
            "WHERE p.phase = 'verify' AND NOT EXISTS ("
            "SELECT 1 FROM phase_snapshots existing "
            "WHERE existing.story_id = p.story_id "
            "AND existing.phase = 'implementation')"
        ),
        "DELETE FROM phase_snapshots WHERE phase = 'verify'",
        (
            "UPDATE attempt_records a SET phase = 'implementation' "
            "WHERE a.phase = 'verify' AND NOT EXISTS ("
            "SELECT 1 FROM attempt_records existing "
            "WHERE existing.story_id = a.story_id "
            "AND existing.phase = 'implementation' "
            "AND existing.seq = a.seq)"
        ),
        "DELETE FROM attempt_records WHERE phase = 'verify'",
    )


def _ensure_reporting_indexes(conn: _CompatConnection) -> None:
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS artifact_records_scope_identity_idx
        ON artifact_records (project_key, run_id, artifact_id)
        """
    )
    conn.execute(
        "ALTER TABLE decision_records DROP CONSTRAINT IF EXISTS decision_records_pkey"
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS decision_records_scope_identity_idx
        ON decision_records (project_key, run_id, decision_kind, attempt_nr)
        """
    )


def _ensure_story_identity_constraints(conn: _CompatConnection) -> None:
    """Apply idempotent story-identity constraints.

    Rollback plan: drop ``story_contexts_project_key_fkey``,
    ``story_contexts_story_uuid_idx``,
    ``story_contexts_project_story_number_idx`` and
    ``story_number_counters``. The migration leaves legacy ``story_id`` columns
    untouched and backfills ``story_number`` from their numeric suffix.
    """

    conn.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'story_contexts_project_key_fkey'
            ) THEN
                ALTER TABLE story_contexts
                ADD CONSTRAINT story_contexts_project_key_fkey
                FOREIGN KEY (project_key) REFERENCES projects(key);
            END IF;
        END
        $$;
        """,
    )


def _ensure_schema(conn: _CompatConnection) -> None:
    conn.executescript(_schema_create_script())
    for statement in _schema_alter_statements():
        conn.execute(statement)
    _ensure_reporting_indexes(conn)
    _ensure_story_identity_constraints(conn)


def _story_id_for(story_dir: Path) -> str | None:
    story_id = story_dir.name
    return story_id or None


def _ensure_project_for_story_row(
    conn: _CompatConnection,
    row: dict[str, Any],
) -> None:
    story_id = str(row["story_id"])
    prefix = story_id.split("-", maxsplit=1)[0]
    project_key = str(row["project_key"])
    existing_project = conn.execute(
        "SELECT 1 FROM projects WHERE key = ?",
        (project_key,),
    ).fetchone()
    if existing_project is not None:
        return
    prefix_owner = conn.execute(
        "SELECT key FROM projects WHERE story_id_prefix = ?",
        (prefix,),
    ).fetchone()
    if prefix_owner is not None:
        prefix = _disambiguated_story_prefix(prefix, project_key)
    conn.execute(
        """
        INSERT INTO projects (
            key,
            name,
            story_id_prefix,
            configuration,
            archived_at
        )
        VALUES (
            ?,
            ?,
            ?,
            '{"repo_url":"","default_branch":"main","are_url":null,
              "default_worker_count":1}'::jsonb,
            NULL::TIMESTAMPTZ
        )
        ON CONFLICT(key) DO NOTHING
        """,
        (project_key, project_key, prefix),
    )


def _disambiguated_story_prefix(prefix: str, project_key: str) -> str:
    import hashlib

    suffix = hashlib.md5(project_key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{prefix[:4]}{suffix[:6]}".upper()


def _artifact_id_for(artifact_kind: str, attempt_no: int | None = None) -> str:
    if attempt_no is None:
        return artifact_kind.replace("_", "-")
    return f"{artifact_kind.replace('_', '-')}-attempt-{attempt_no}"


def _artifact_class_for(artifact_kind: str) -> str:
    if artifact_kind == "closure_report":
        return "closure"
    return "qa"


def _produced_in_phase_for(artifact_kind: str) -> str:
    if artifact_kind == "closure_report":
        return "closure"
    return "implementation"


def _producer_trust_for(producer_component: str) -> str:
    if producer_component in {"qa-semantic-review"}:
        return "verified_llm"
    if producer_component in {"qa-adversarial"}:
        return "agent"
    return "system"


def _upsert_artifact_record(
    conn: _CompatConnection,
    *,
    flow_row: dict[str, Any],
    artifact_kind: str,
    artifact_name: str,
    producer_component: str,
    lifecycle_status: str,
    payload: dict[str, object],
    created_at: datetime,
    attempt_no: int | None = None,
) -> str:
    """Insert or update an artifact record using a plain flow_row dict."""

    artifact_id = _artifact_id_for(artifact_kind, attempt_no)
    run_id = str(flow_row["run_id"])
    legacy_artifact_name = f"{artifact_name}@{run_id}"
    conn.execute(
        """
        INSERT INTO artifact_records (
            project_key, story_id, run_id, artifact_id, artifact_class,
            artifact_kind, artifact_format, artifact_status, produced_in_phase,
            artifact_name, producer, producer_component, producer_trust,
            protection_level, frozen, integrity_verified, status, attempt_nr,
            attempt_no, qa_cycle_id, qa_cycle_round, evidence_epoch,
            payload_json, created_at, finished_at, storage_ref
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(project_key, run_id, artifact_id) DO UPDATE SET
            story_id=excluded.story_id,
            artifact_class=excluded.artifact_class,
            artifact_kind=excluded.artifact_kind,
            artifact_format=excluded.artifact_format,
            artifact_status=excluded.artifact_status,
            produced_in_phase=excluded.produced_in_phase,
            artifact_name=excluded.artifact_name,
            producer=excluded.producer,
            producer_component=excluded.producer_component,
            producer_trust=excluded.producer_trust,
            protection_level=excluded.protection_level,
            frozen=excluded.frozen,
            integrity_verified=excluded.integrity_verified,
            status=excluded.status,
            attempt_nr=excluded.attempt_nr,
            attempt_no=excluded.attempt_no,
            qa_cycle_id=excluded.qa_cycle_id,
            qa_cycle_round=excluded.qa_cycle_round,
            evidence_epoch=excluded.evidence_epoch,
            payload_json=excluded.payload_json,
            created_at=excluded.created_at,
            finished_at=excluded.finished_at,
            storage_ref=excluded.storage_ref
        """,
        (
            flow_row["project_key"],
            flow_row["story_id"],
            run_id,
            artifact_id,
            _artifact_class_for(artifact_kind),
            artifact_kind,
            "json",
            "produced",
            _produced_in_phase_for(artifact_kind),
            legacy_artifact_name,
            producer_component,
            producer_component,
            _producer_trust_for(producer_component),
            "hook_locked",
            0,
            0,
            lifecycle_status,
            attempt_no if attempt_no is not None else 0,
            attempt_no,
            (
                f"verify-attempt-{attempt_no}"
                if attempt_no is not None and artifact_kind != "closure_report"
                else None
            ),
            attempt_no,
            attempt_no,
            _dump_json(payload),
            created_at.isoformat(),
            created_at.isoformat(),
            artifact_name,
        ),
    )
    return artifact_id


# ---------------------------------------------------------------------------
# StoryContext rows
# ---------------------------------------------------------------------------


def save_story_context_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a story-context row dict to the database and projection file."""

    payload_dict = json.loads(str(row["payload_json"]))
    with _connect(story_dir) as conn:
        _ensure_project_for_story_row(conn, row)
        conn.execute(
            """
            INSERT INTO story_contexts (
                story_uuid,
                project_key,
                story_number,
                story_id,
                story_type,
                execution_route,
                implementation_contract,
                issue_nr,
                title,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, story_id) DO UPDATE SET
                story_uuid=excluded.story_uuid,
                story_number=excluded.story_number,
                story_type=excluded.story_type,
                execution_route=excluded.execution_route,
                implementation_contract=excluded.implementation_contract,
                issue_nr=excluded.issue_nr,
                title=excluded.title,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                row["story_uuid"],
                row["project_key"],
                row["story_number"],
                row["story_id"],
                row["story_type"],
                row["execution_route"],
                row["implementation_contract"],
                row["issue_nr"],
                row["title"],
                row["payload_json"],
                now_iso(),
            ),
        )
    _write_projection(story_dir / CONTEXT_EXPORT_FILE, payload_dict)


def load_story_context_row(story_dir: Path) -> dict[str, Any] | None:
    """Return the raw payload row for a story context, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        rows = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise CorruptStateError(
            "story_contexts lookup is ambiguous without explicit project scope",
            detail={"story_dir": str(story_dir), "story_id": story_id},
        )
    return {"payload_json": str(rows[0]["payload_json"])}


def read_story_context_row(story_dir: Path) -> dict[str, Any] | None:
    """Canonical reader name for protected runtime modules."""

    return load_story_context_row(story_dir)


def save_story_context_global_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist a story-context row without requiring a story directory."""

    del store_dir
    with _connect_global() as conn:
        _ensure_project_for_story_row(conn, row)
        conn.execute(
            """
            INSERT INTO story_contexts (
                story_uuid,
                project_key,
                story_number,
                story_id,
                story_type,
                execution_route,
                implementation_contract,
                issue_nr,
                title,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, story_id) DO UPDATE SET
                story_uuid=excluded.story_uuid,
                story_number=excluded.story_number,
                story_type=excluded.story_type,
                execution_route=excluded.execution_route,
                implementation_contract=excluded.implementation_contract,
                issue_nr=excluded.issue_nr,
                title=excluded.title,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                row["story_uuid"],
                row["project_key"],
                row["story_number"],
                row["story_id"],
                row["story_type"],
                row["execution_route"],
                row["implementation_contract"],
                row["issue_nr"],
                row["title"],
                row["payload_json"],
                now_iso(),
            ),
        )


def load_story_context_global_row(
    store_dir: Path | None,
    project_key: str,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the raw payload row for a global story context, or None."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE project_key = ? AND story_id = ?
            """,
            (project_key, story_id),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def load_story_context_by_story_number_row(
    store_dir: Path | None,
    project_key: str,
    story_number: int,
) -> dict[str, Any] | None:
    """Return one story-context row by fachliche identity."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE project_key = ? AND story_number = ?
            """,
            (project_key, story_number),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def load_story_context_by_uuid_row(
    store_dir: Path | None,
    story_uuid: str,
) -> dict[str, Any] | None:
    """Return one story-context row by technical identity."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE story_uuid = ?::uuid
            """,
            (story_uuid,),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def allocate_next_story_number_row(store_dir: Path | None, project_key: str) -> int:
    """Atomically reserve the next story number for one project."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            INSERT INTO story_number_counters (project_key, next_story_number)
            VALUES (?, 2)
            ON CONFLICT(project_key) DO UPDATE SET
                next_story_number = story_number_counters.next_story_number + 1
            RETURNING next_story_number - 1 AS allocated_story_number
            """,
            (project_key,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Story-number allocation failed")
    return int(row["allocated_story_number"])


def load_story_context_rows_global(
    store_dir: Path | None,
    project_key: str,
) -> list[dict[str, Any]]:
    """Return all raw payload rows for a project's story contexts."""

    del store_dir
    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE project_key = ?
            ORDER BY story_id ASC
            """,
            (project_key,),
        ).fetchall()
    return [{"payload_json": str(row["payload_json"])} for row in rows]


# ---------------------------------------------------------------------------
# Execution planning rows
# ---------------------------------------------------------------------------


def save_story_dependency_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist one story dependency row.

    Migration note: ``story_dependencies`` is created idempotently by
    ``_schema_create_script``. Rollback is ``DROP TABLE story_dependencies``
    after dropping dependent indexes; no existing story-context data is
    modified.
    """

    del store_dir
    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO story_dependencies (
                project_key,
                story_id,
                depends_on_story_id,
                kind,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                row["project_key"],
                row["story_id"],
                row["depends_on_story_id"],
                row["kind"],
                row["created_at"],
            ),
        )


def load_story_dependency_rows(
    store_dir: Path | None,
    project_key: str,
) -> list[dict[str, Any]]:
    """Load all dependency rows for one project."""

    del store_dir
    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT project_key, story_id, depends_on_story_id, kind, created_at
            FROM story_dependencies
            WHERE project_key = ?
            ORDER BY story_id, depends_on_story_id, kind
            """,
            (project_key,),
        ).fetchall()
    return rows


def load_story_dependency_rows_for_story(
    store_dir: Path | None,
    story_id: str,
) -> list[dict[str, Any]]:
    """Load direct predecessor dependency rows for one story."""

    del store_dir
    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT project_key, story_id, depends_on_story_id, kind, created_at
            FROM story_dependencies
            WHERE story_id = ?
            ORDER BY project_key, depends_on_story_id, kind
            """,
            (story_id,),
        ).fetchall()
    return rows


def delete_story_dependency_row(
    store_dir: Path | None,
    story_id: str,
    depends_on_story_id: str,
    kind: str,
) -> int:
    """Delete one dependency row and return affected row count."""

    del store_dir
    with _connect_global() as conn:
        cursor = conn.execute(
            """
            DELETE FROM story_dependencies
            WHERE story_id = ? AND depends_on_story_id = ? AND kind = ?
            """,
            (story_id, depends_on_story_id, kind),
        )
        return int(cursor.rowcount)


def save_parallelization_config_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist one parallelization config row."""

    del store_dir
    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO parallelization_configs (
                project_key,
                max_parallel_stories,
                max_parallel_stories_per_repo,
                extra_config,
                updated_at
            ) VALUES (?, ?, ?, ?::jsonb, now())
            ON CONFLICT(project_key) DO UPDATE SET
                max_parallel_stories = excluded.max_parallel_stories,
                max_parallel_stories_per_repo =
                    excluded.max_parallel_stories_per_repo,
                extra_config = excluded.extra_config,
                updated_at = excluded.updated_at
            """,
            (
                row["project_key"],
                row["max_parallel_stories"],
                row["max_parallel_stories_per_repo"],
                row["extra_config_json"],
            ),
        )


def load_parallelization_config_row(
    store_dir: Path | None,
    project_key: str,
) -> dict[str, Any] | None:
    """Load one parallelization config row."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT
                project_key,
                max_parallel_stories,
                max_parallel_stories_per_repo,
                extra_config AS extra_config_json
            FROM parallelization_configs
            WHERE project_key = ?
            """,
            (project_key,),
        ).fetchone()
    return row


# ---------------------------------------------------------------------------
# Project rows
# ---------------------------------------------------------------------------


def save_project_row(store_dir: Path | None, row: dict[str, Any]) -> None:
    """Persist a project row."""

    del store_dir
    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO projects (
                key,
                name,
                story_id_prefix,
                configuration,
                archived_at
            )
            VALUES (?, ?, ?, ?::jsonb, ?)
            ON CONFLICT(key) DO UPDATE SET
                name = excluded.name,
                configuration = excluded.configuration,
                archived_at = excluded.archived_at
            """,
            (
                row["key"],
                row["name"],
                row["story_id_prefix"],
                row["configuration_json"],
                row["archived_at"],
            ),
        )


def load_project_row(store_dir: Path | None, key: str) -> dict[str, Any] | None:
    """Load one project row by key."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT
                key,
                name,
                story_id_prefix,
                configuration AS configuration_json,
                archived_at
            FROM projects
            WHERE key = ?
            """,
            (key,),
        ).fetchone()
    return row


def load_project_row_by_story_id_prefix(
    store_dir: Path | None,
    story_id_prefix: str,
) -> dict[str, Any] | None:
    """Load one project row by story-id prefix."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT
                key,
                name,
                story_id_prefix,
                configuration AS configuration_json,
                archived_at
            FROM projects
            WHERE story_id_prefix = ?
            """,
            (story_id_prefix,),
        ).fetchone()
    return row


def load_project_rows(
    store_dir: Path | None,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Load project rows."""

    del store_dir
    query = """
        SELECT
            key,
            name,
            story_id_prefix,
            configuration AS configuration_json,
            archived_at
        FROM projects
        ORDER BY key
        """
    if not include_archived:
        query = """
            SELECT
                key,
                name,
                story_id_prefix,
                configuration AS configuration_json,
                archived_at
            FROM projects
            WHERE archived_at IS NULL
            ORDER BY key
            """
    with _connect_global() as conn:
        rows = conn.execute(query).fetchall()
    return rows


# ---------------------------------------------------------------------------
# PhaseState rows
# ---------------------------------------------------------------------------


def save_phase_state_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a phase-state row dict to the database and projection file."""

    payload_dict = json.loads(str(row["payload_json"]))
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO phase_states (
                story_id, phase, status, paused_reason, review_round,
                attempt_id, errors_json, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                phase=excluded.phase,
                status=excluded.status,
                paused_reason=excluded.paused_reason,
                review_round=excluded.review_round,
                attempt_id=excluded.attempt_id,
                errors_json=excluded.errors_json,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                row["story_id"],
                row["phase"],
                row["status"],
                row["paused_reason"],
                row["review_round"],
                row["attempt_id"],
                row["errors_json"],
                row["payload_json"],
                now_iso(),
            ),
        )
    _write_projection(story_dir / PHASE_STATE_EXPORT_FILE, payload_dict)


def load_phase_state_row(story_dir: Path) -> dict[str, Any] | None:
    """Return the raw payload row for a phase state, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM phase_states
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def read_phase_state_row(story_dir: Path) -> dict[str, Any] | None:
    """Canonical reader name for protected runtime modules."""

    return load_phase_state_row(story_dir)


def load_phase_state_global_row(
    store_dir: Path | None,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the raw payload row for a global phase state, or None."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM phase_states
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


# ---------------------------------------------------------------------------
# PhaseSnapshot rows
# ---------------------------------------------------------------------------


def save_phase_snapshot_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a phase-snapshot row dict to the database and projection file."""

    payload_dict = json.loads(str(row["payload_json"]))
    phase = str(row["phase"])
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO phase_snapshots (
                story_id, phase, status, completed_at, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(story_id, phase) DO UPDATE SET
                status=excluded.status,
                completed_at=excluded.completed_at,
                payload_json=excluded.payload_json
            """,
            (
                row["story_id"],
                row["phase"],
                row["status"],
                row["completed_at"],
                row["payload_json"],
            ),
        )
    _write_projection(story_dir / f"phase-state-{phase}.json", payload_dict)


def load_phase_snapshot_row(story_dir: Path, phase: str) -> dict[str, Any] | None:
    """Return the raw payload row for a phase snapshot, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM phase_snapshots
            WHERE story_id = ? AND phase = ?
            """,
            (story_id, phase),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def read_phase_snapshot_row(story_dir: Path, phase: str) -> dict[str, Any] | None:
    """Canonical reader name for protected runtime modules."""

    return load_phase_snapshot_row(story_dir, phase)


# ---------------------------------------------------------------------------
# AttemptRecord rows
# ---------------------------------------------------------------------------


def save_attempt_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist an attempt row dict to the database."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist attempt without story context in canonical backend",
        )
    with _connect(story_dir) as conn:
        max_row = conn.execute(
            """
            SELECT COALESCE(MAX(seq), 0) AS max_seq
            FROM attempt_records
            WHERE story_id = ? AND phase = ?
            """,
            (story_id, row["phase"]),
        ).fetchone()
        seq = int(max_row["max_seq"]) + 1 if max_row is not None else 1
        conn.execute(
            """
            INSERT INTO attempt_records (
                story_id, phase, seq, attempt_id, entered_at, exit_status,
                outcome, yield_status, resume_trigger,
                guard_evaluations_json, artifacts_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story_id,
                row["phase"],
                seq,
                row["attempt_id"],
                row["entered_at"],
                row["exit_status"],
                row["outcome"],
                row["yield_status"],
                row["resume_trigger"],
                row["guard_evaluations_json"],
                row["artifacts_json"],
            ),
        )


def load_attempt_rows(story_dir: Path, phase: str) -> list[dict[str, Any]]:
    """Return attempt row dicts for a given phase, ordered by seq."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return []
    with _connect(story_dir) as conn:
        rows = conn.execute(
            """
            SELECT * FROM attempt_records
            WHERE story_id = ? AND phase = ?
            ORDER BY seq ASC
            """,
            (story_id, phase),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# FlowExecution rows
# ---------------------------------------------------------------------------


def save_flow_execution_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a flow-execution row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO flow_executions (
                story_id, project_key, run_id, flow_id, level, owner,
                parent_flow_id, status, current_node_id, attempt_no,
                started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                project_key=excluded.project_key,
                run_id=excluded.run_id,
                flow_id=excluded.flow_id,
                level=excluded.level,
                owner=excluded.owner,
                parent_flow_id=excluded.parent_flow_id,
                status=excluded.status,
                current_node_id=excluded.current_node_id,
                attempt_no=excluded.attempt_no,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at
            """,
            (
                row["story_id"],
                row["project_key"],
                row["run_id"],
                row["flow_id"],
                row["level"],
                row["owner"],
                row["parent_flow_id"],
                row["status"],
                row["current_node_id"],
                row["attempt_no"],
                row["started_at"],
                row["finished_at"],
            ),
        )


def load_flow_execution_row(story_dir: Path) -> dict[str, Any] | None:
    """Return the raw flow-execution row, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT * FROM flow_executions
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def load_flow_execution_global_row(
    project_key: str,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the raw flow-execution row for a global lookup, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM flow_executions
            WHERE project_key = ? AND story_id = ?
            """,
            (project_key, story_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# ExecutionEventRecord rows
# ---------------------------------------------------------------------------


def _insert_execution_event_row(
    conn: _CompatConnection,
    row: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO execution_events (
            project_key, story_id, run_id, event_id, event_type,
            occurred_at, source_component, severity, phase, flow_id,
            node_id, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["project_key"],
            row["story_id"],
            row["run_id"],
            row["event_id"],
            row["event_type"],
            row["occurred_at"],
            row["source_component"],
            row["severity"],
            row["phase"],
            row["flow_id"],
            row["node_id"],
            row["payload_json"],
        ),
    )


def append_execution_event_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist an execution-event row dict to the database."""

    with _connect(story_dir) as conn:
        _insert_execution_event_row(conn, row)


def append_execution_event_global_row(row: dict[str, Any]) -> None:
    """Persist an execution-event row dict globally."""

    with _connect_global() as conn:
        _insert_execution_event_row(conn, row)


def load_execution_event_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return execution-event row dicts matching the given filters."""

    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT project_key, story_id, run_id, event_id, event_type,
                   occurred_at, source_component, severity, phase, flow_id,
                   node_id, payload_json
            FROM execution_events
            {where_clause}
            ORDER BY occurred_at ASC, event_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def load_execution_event_rows_global(
    project_key: str,
    story_id: str,
    *,
    run_id: str | None = None,
    event_type: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return execution-event row dicts for a global project/story query."""

    if limit is not None and limit <= 0:
        return []
    clauses = [_PROJECT_KEY_FILTER, _STORY_ID_FILTER]
    params: list[object] = [project_key, story_id]
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT ?"
        params.append(limit)
    where_clause = f"WHERE {' AND '.join(clauses)}"
    with _connect_global() as conn:
        rows = conn.execute(
            f"""
            SELECT project_key, story_id, run_id, event_id, event_type,
                   occurred_at, source_component, severity, phase, flow_id,
                   node_id, payload_json
            FROM execution_events
            {where_clause}
            ORDER BY occurred_at DESC, event_id DESC
            {limit_clause}
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


# ---------------------------------------------------------------------------
# SessionRunBindingRecord rows
# ---------------------------------------------------------------------------


def save_session_run_binding_global_row(row: dict[str, Any]) -> None:
    """Persist a session-run-binding row dict globally."""

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO session_run_bindings (
                session_id, project_key, story_id, run_id, principal_type,
                worktree_roots_json, binding_version, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE SET
                project_key = EXCLUDED.project_key,
                story_id = EXCLUDED.story_id,
                run_id = EXCLUDED.run_id,
                principal_type = EXCLUDED.principal_type,
                worktree_roots_json = EXCLUDED.worktree_roots_json,
                binding_version = EXCLUDED.binding_version,
                updated_at = EXCLUDED.updated_at
            """,
            (
                row["session_id"],
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["principal_type"],
                row["worktree_roots_json"],
                row["binding_version"],
                row["updated_at"],
            ),
        )


def load_session_run_binding_global_row(
    session_id: str,
) -> dict[str, Any] | None:
    """Return the raw session-run-binding row for a session, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM session_run_bindings
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def delete_session_run_binding_global(session_id: str) -> None:
    """Delete a session-run-binding globally."""

    with _connect_global() as conn:
        conn.execute(
            """
            DELETE FROM session_run_bindings
            WHERE session_id = ?
            """,
            (session_id,),
        )


# ---------------------------------------------------------------------------
# StoryExecutionLockRecord rows
# ---------------------------------------------------------------------------


def save_story_execution_lock_global_row(row: dict[str, Any]) -> None:
    """Persist a story-execution-lock row dict globally."""

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO story_execution_locks (
                project_key, story_id, run_id, lock_type, status,
                worktree_roots_json, binding_version, activated_at,
                updated_at, deactivated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (project_key, run_id, lock_type) DO UPDATE SET
                story_id = EXCLUDED.story_id,
                status = EXCLUDED.status,
                worktree_roots_json = EXCLUDED.worktree_roots_json,
                binding_version = EXCLUDED.binding_version,
                activated_at = EXCLUDED.activated_at,
                updated_at = EXCLUDED.updated_at,
                deactivated_at = EXCLUDED.deactivated_at
            """,
            (
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["lock_type"],
                row["status"],
                row["worktree_roots_json"],
                row["binding_version"],
                row["activated_at"],
                row["updated_at"],
                row["deactivated_at"],
            ),
        )


def load_story_execution_lock_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
    lock_type: str = "story_execution",
) -> dict[str, Any] | None:
    """Return the raw story-execution-lock row, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM story_execution_locks
            WHERE project_key = ? AND story_id = ? AND run_id = ? AND lock_type = ?
            """,
            (project_key, story_id, run_id, lock_type),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# ControlPlaneOperationRecord rows
# ---------------------------------------------------------------------------


def save_control_plane_operation_global_row(row: dict[str, Any]) -> None:
    """Persist a control-plane-operation row dict globally."""

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO control_plane_operations (
                op_id, project_key, story_id, run_id, session_id,
                operation_kind, phase, status, response_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (op_id) DO UPDATE SET
                project_key = EXCLUDED.project_key,
                story_id = EXCLUDED.story_id,
                run_id = EXCLUDED.run_id,
                session_id = EXCLUDED.session_id,
                operation_kind = EXCLUDED.operation_kind,
                phase = EXCLUDED.phase,
                status = EXCLUDED.status,
                response_json = EXCLUDED.response_json,
                updated_at = EXCLUDED.updated_at
            """,
            (
                row["op_id"],
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["session_id"],
                row["operation_kind"],
                row["phase"],
                row["status"],
                row["response_json"],
                row["created_at"],
                row["updated_at"],
            ),
        )


def load_control_plane_operation_global_row(
    op_id: str,
) -> dict[str, Any] | None:
    """Return the raw control-plane-operation row, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM control_plane_operations
            WHERE op_id = ?
            """,
            (op_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# StoryMetricsRecord rows
# ---------------------------------------------------------------------------


def upsert_story_metrics_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a story-metrics row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO story_metrics (
                project_key, story_id, run_id, story_type, story_size, mode,
                processing_time_min, qa_rounds, increments, final_status,
                completed_at, adversarial_findings, adversarial_tests_created,
                files_changed, agentkit_version, agentkit_commit,
                config_version, llm_roles_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, run_id) DO UPDATE SET
                story_id=excluded.story_id,
                story_type=excluded.story_type,
                story_size=excluded.story_size,
                mode=excluded.mode,
                processing_time_min=excluded.processing_time_min,
                qa_rounds=excluded.qa_rounds,
                increments=excluded.increments,
                final_status=excluded.final_status,
                completed_at=excluded.completed_at,
                adversarial_findings=excluded.adversarial_findings,
                adversarial_tests_created=excluded.adversarial_tests_created,
                files_changed=excluded.files_changed,
                agentkit_version=excluded.agentkit_version,
                agentkit_commit=excluded.agentkit_commit,
                config_version=excluded.config_version,
                llm_roles_json=excluded.llm_roles_json
            """,
            (
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["story_type"],
                row["story_size"],
                row["mode"],
                row["processing_time_min"],
                row["qa_rounds"],
                row["increments"],
                row["final_status"],
                row["completed_at"],
                row["adversarial_findings"],
                row["adversarial_tests_created"],
                row["files_changed"],
                row["agentkit_version"],
                row["agentkit_commit"],
                row["config_version"],
                row["llm_roles_json"],
            ),
        )


def load_story_metrics_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return story-metrics row dicts matching the given filters."""

    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM story_metrics
            {where_clause}
            ORDER BY completed_at ASC, run_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def load_latest_story_metrics_global_row(
    store_dir: Path | None,
    project_key: str,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the latest raw story-metrics row for a global lookup, or None."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM story_metrics
            WHERE project_key = ? AND story_id = ?
            ORDER BY completed_at DESC, run_id DESC
            LIMIT 1
            """,
            (project_key, story_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# NodeExecutionLedger rows
# ---------------------------------------------------------------------------


def save_node_execution_ledger_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a node-execution-ledger row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO node_execution_ledgers (
                story_id, flow_id, node_id, project_key, run_id,
                execution_count, success_count, last_outcome,
                last_attempt_no, last_executed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id, flow_id, node_id) DO UPDATE SET
                project_key=excluded.project_key,
                run_id=excluded.run_id,
                execution_count=excluded.execution_count,
                success_count=excluded.success_count,
                last_outcome=excluded.last_outcome,
                last_attempt_no=excluded.last_attempt_no,
                last_executed_at=excluded.last_executed_at
            """,
            (
                row["story_id"],
                row["flow_id"],
                row["node_id"],
                row["project_key"],
                row["run_id"],
                row["execution_count"],
                row["success_count"],
                row["last_outcome"],
                row["last_attempt_no"],
                row["last_executed_at"],
            ),
        )


def load_node_execution_ledger_row(
    story_dir: Path,
    flow_id: str,
    node_id: str,
) -> dict[str, Any] | None:
    """Return the raw node-execution-ledger row, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT * FROM node_execution_ledgers
            WHERE story_id = ? AND flow_id = ? AND node_id = ?
            """,
            (story_id, flow_id, node_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# OverrideRecord rows
# ---------------------------------------------------------------------------


def save_override_record_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist an override-record row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO override_records (
                override_id, story_id, project_key, run_id, flow_id,
                target_node_id, override_type, actor_type, actor_id,
                reason, created_at, consumed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(override_id) DO UPDATE SET
                target_node_id=excluded.target_node_id,
                override_type=excluded.override_type,
                actor_type=excluded.actor_type,
                actor_id=excluded.actor_id,
                reason=excluded.reason,
                created_at=excluded.created_at,
                consumed_at=excluded.consumed_at
            """,
            (
                row["override_id"],
                row["story_id"],
                row["project_key"],
                row["run_id"],
                row["flow_id"],
                row["target_node_id"],
                row["override_type"],
                row["actor_type"],
                row["actor_id"],
                row["reason"],
                row["created_at"],
                row["consumed_at"],
            ),
        )


def load_override_record_rows(story_dir: Path) -> list[dict[str, Any]]:
    """Return override-record row dicts for a story, ordered by created_at."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return []
    with _connect(story_dir) as conn:
        rows = conn.execute(
            """
            SELECT * FROM override_records
            WHERE story_id = ?
            ORDER BY created_at ASC
            """,
            (story_id,),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# QA layer artifacts + QA decision
# ---------------------------------------------------------------------------


def persist_layer_artifact_rows(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    layer_payload_rows: list[dict[str, object]],
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist QA layer artifact rows, FK-69 read models, and projection files.

    ``layer_payload_rows`` contains pre-serialized dicts from the mapper layer.
    Each element has keys: ``layer``, ``artifact_name``, ``producer_component``,
    ``payload``, ``passed``, ``recorded_at``, ``stage_row``, ``finding_rows``.
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist QA layer artifacts without story context "
            "in canonical backend",
        )
    if flow_row is None:
        raise CorruptStateError(
            "Cannot materialize FK-69 QA read models without flow execution "
            "scope in canonical Postgres backend",
        )
    produced: list[str] = []
    with _connect(story_dir) as conn:
        for item in layer_payload_rows:
            layer = str(item["layer"])
            artifact_name = str(item["artifact_name"])
            producer_component = str(item["producer_component"])
            payload = cast("_JsonRecord", item["payload"])
            passed = bool(item["passed"])
            recorded_at = datetime.fromisoformat(str(item["recorded_at"]))
            target_dir = projection_dir or story_dir
            _write_projection(target_dir / artifact_name, payload)
            artifact_id = _upsert_artifact_record(
                conn,
                flow_row=flow_row,
                artifact_kind=layer,
                artifact_name=artifact_name,
                producer_component=producer_component,
                lifecycle_status="PASS" if passed else "FAIL",
                payload=payload,
                created_at=recorded_at,
                attempt_no=attempt_nr,
            )
            # FK-69: delete old findings for this scope + layer
            conn.execute(
                """
                DELETE FROM qa_findings
                WHERE project_key = ? AND run_id = ? AND attempt_no = ? AND stage_id = ?
                """,
                (
                    flow_row["project_key"],
                    flow_row["run_id"],
                    attempt_nr,
                    layer,
                ),
            )
            # Rebuild stage_row and finding_rows with the real artifact_id
            stage_row = cast("dict[str, object] | None", item.get("stage_row"))
            finding_rows = cast(
                "list[dict[str, object]]", item.get("finding_rows") or []
            )
            if stage_row is not None:
                # Replace placeholder artifact_id with real one
                updated_stage = dict(stage_row)
                updated_stage["artifact_id"] = artifact_id
                conn.execute(
                    """
                    INSERT INTO qa_stage_results (
                        project_key, story_id, run_id, attempt_no, stage_id, layer,
                        producer_component, status, blocking, total_checks,
                        failed_checks, warning_checks, artifact_id, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_key, run_id, attempt_no, stage_id)
                    DO UPDATE SET
                        story_id=excluded.story_id,
                        layer=excluded.layer,
                        producer_component=excluded.producer_component,
                        status=excluded.status,
                        blocking=excluded.blocking,
                        total_checks=excluded.total_checks,
                        failed_checks=excluded.failed_checks,
                        warning_checks=excluded.warning_checks,
                        artifact_id=excluded.artifact_id,
                        recorded_at=excluded.recorded_at
                    """,
                    (
                        updated_stage["project_key"],
                        updated_stage["story_id"],
                        updated_stage["run_id"],
                        updated_stage["attempt_no"],
                        updated_stage["stage_id"],
                        updated_stage["layer"],
                        updated_stage["producer_component"],
                        updated_stage["status"],
                        updated_stage["blocking"],
                        updated_stage["total_checks"],
                        updated_stage["failed_checks"],
                        updated_stage["warning_checks"],
                        updated_stage["artifact_id"],
                        updated_stage["recorded_at"],
                    ),
                )
            for fr in finding_rows:
                updated_fr = dict(fr)
                updated_fr["artifact_id"] = artifact_id
                conn.execute(
                    """
                    INSERT INTO qa_findings (
                        project_key, story_id, run_id, attempt_no, stage_id,
                        finding_id, check_id, status, severity, blocking,
                        source_component, artifact_id, occurred_at, category,
                        reason, description, detail, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_key, run_id, attempt_no, stage_id, finding_id)
                    DO UPDATE SET
                        story_id=excluded.story_id,
                        check_id=excluded.check_id,
                        status=excluded.status,
                        severity=excluded.severity,
                        blocking=excluded.blocking,
                        source_component=excluded.source_component,
                        artifact_id=excluded.artifact_id,
                        occurred_at=excluded.occurred_at,
                        category=excluded.category,
                        reason=excluded.reason,
                        description=excluded.description,
                        detail=excluded.detail,
                        metadata_json=excluded.metadata_json
                    """,
                    (
                        updated_fr["project_key"],
                        updated_fr["story_id"],
                        updated_fr["run_id"],
                        updated_fr["attempt_no"],
                        updated_fr["stage_id"],
                        updated_fr["finding_id"],
                        updated_fr["check_id"],
                        updated_fr["status"],
                        updated_fr["severity"],
                        updated_fr["blocking"],
                        updated_fr["source_component"],
                        updated_fr["artifact_id"],
                        updated_fr["occurred_at"],
                        updated_fr["category"],
                        updated_fr["reason"],
                        updated_fr["description"],
                        updated_fr["detail"],
                        updated_fr["metadata_json"],
                    ),
                )
            produced.append(artifact_name)
    return tuple(produced)


def persist_verify_decision_row(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    decision_row: dict[str, Any],
    canonical_payload: dict[str, object],
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist a verify-decision row and write the projection file."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist verify decision without story context in canonical backend",
        )
    if flow_row is None:
        raise CorruptStateError(
            "Cannot persist verify decision artifact without flow execution "
            "scope in canonical Postgres backend",
        )
    target_dir = projection_dir or story_dir
    _write_projection(target_dir / VERIFY_DECISION_FILE, canonical_payload)
    written = (VERIFY_DECISION_FILE,)
    with _connect(story_dir) as conn:
        recorded_at = datetime.fromisoformat(now_iso())
        conn.execute(
            """
            INSERT INTO decision_records (
                project_key, story_id, run_id, flow_id, decision_kind,
                attempt_nr, status, passed, summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, run_id, decision_kind, attempt_nr)
            DO UPDATE SET
                story_id=excluded.story_id,
                flow_id=excluded.flow_id,
                status=excluded.status,
                passed=excluded.passed,
                summary=excluded.summary,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                flow_row["project_key"],
                story_id,
                flow_row["run_id"],
                flow_row["flow_id"],
                "verify",
                attempt_nr,
                decision_row["status"],
                1 if decision_row["passed"] else 0,
                decision_row["summary"],
                _dump_json(canonical_payload),
                recorded_at.isoformat(),
            ),
        )
        _upsert_artifact_record(
            conn,
            flow_row=flow_row,
            artifact_kind="verify_decision",
            artifact_name=written[0],
            producer_component="qa-policy-engine",
            lifecycle_status=str(decision_row["status"]),
            payload=canonical_payload,
            created_at=recorded_at,
            attempt_no=attempt_nr,
        )
    return written


def load_latest_verify_decision_payload(
    story_dir: Path,
) -> dict[str, object] | None:
    """Return the latest verify-decision payload dict, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    flow_row = load_flow_execution_row(story_dir)
    with _connect(story_dir) as conn:
        if flow_row is not None:
            row = conn.execute(
                """
                SELECT payload_json
                FROM decision_records
                WHERE project_key = ? AND story_id = ? AND run_id = ?
                  AND decision_kind = 'verify'
                ORDER BY attempt_nr DESC
                LIMIT 1
                """,
                (flow_row["project_key"], flow_row["story_id"], flow_row["run_id"]),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    SELECT payload_json
                    FROM decision_records
                    WHERE story_id = ? AND decision_kind = 'verify'
                    ORDER BY attempt_nr DESC
                    LIMIT 1
                    """,
                    (story_id,),
                ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT payload_json
                FROM decision_records
                WHERE story_id = ? AND decision_kind = 'verify'
                ORDER BY attempt_nr DESC
                LIMIT 1
                """,
                (story_id,),
            ).fetchone()
    if row is None:
        return None
    try:
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"decision_records payload is invalid in {_database_label()}: {exc}",
        ) from exc


def load_latest_verify_decision_payload_for_scope(
    scope: RuntimeStateScope,
) -> dict[str, object] | None:
    """Return the latest verify-decision payload for a scope, or None."""

    with _connect(scope.story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json
            FROM decision_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND decision_kind = 'verify'
            ORDER BY attempt_nr DESC
            LIMIT 1
            """,
            (scope.project_key, scope.story_id, scope.run_id),
        ).fetchone()
    if row is None:
        return None
    try:
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"decision_records payload is invalid in {_database_label()}: {exc}",
        ) from exc


def load_artifact_record_payload(
    story_dir: Path,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Return the latest artifact payload dict for a kind, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    flow_row = load_flow_execution_row(story_dir)
    with _connect(story_dir) as conn:
        if flow_row is not None:
            row = conn.execute(
                """
                SELECT payload_json
                FROM artifact_records
                WHERE project_key = ? AND story_id = ? AND run_id = ?
                  AND artifact_kind = ?
                ORDER BY attempt_no DESC NULLS LAST, created_at DESC
                LIMIT 1
                """,
                (
                    flow_row["project_key"],
                    flow_row["story_id"],
                    flow_row["run_id"],
                    artifact_kind,
                ),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT payload_json
                FROM artifact_records
                WHERE story_id = ? AND artifact_kind = ?
                ORDER BY attempt_nr DESC, created_at DESC
                LIMIT 1
                """,
                (story_id, artifact_kind),
            ).fetchone()
    if row is None:
        return None
    try:
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"artifact_records payload is invalid in {_database_label()}: {exc}",
        ) from exc


def load_artifact_record_payload_for_scope(
    scope: RuntimeStateScope,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Return the latest artifact payload for a scope and kind, or None."""

    with _connect(scope.story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json
            FROM artifact_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND artifact_kind = ?
            ORDER BY attempt_no DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            (scope.project_key, scope.story_id, scope.run_id, artifact_kind),
        ).fetchone()
    if row is None:
        return None
    try:
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"artifact_records payload is invalid in {_database_label()}: {exc}",
        ) from exc


def persist_closure_report_row(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    report_row: dict[str, Any],
    projection_dir: Path | None = None,
) -> Path:
    """Persist a closure-report and write the projection file."""

    if flow_row is None:
        raise CorruptStateError(
            "Cannot persist closure artifact without flow execution scope "
            "in canonical Postgres backend",
        )
    target_dir = projection_dir or story_dir
    path = target_dir / CLOSURE_REPORT_FILE
    payload = cast("_JsonRecord", report_row["payload"])
    _write_projection(path, payload)
    with _connect(story_dir) as conn:
        _upsert_artifact_record(
            conn,
            flow_row=flow_row,
            artifact_kind="closure_report",
            artifact_name=path.name,
            producer_component="story-closure",
            lifecycle_status=str(report_row["status"]).upper(),
            payload=payload,
            created_at=datetime.fromisoformat(now_iso()),
        )
    return path


# ---------------------------------------------------------------------------
# QA read models (Postgres-only)
# ---------------------------------------------------------------------------


def load_qa_stage_result_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return QA stage result row dicts matching the given filters."""

    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if attempt_no is not None:
        clauses.append("attempt_no = ?")
        params.append(attempt_no)
    if stage_id is not None:
        clauses.append("stage_id = ?")
        params.append(stage_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM qa_stage_results
            {where_clause}
            ORDER BY attempt_no ASC, stage_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def load_qa_finding_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return QA finding row dicts matching the given filters."""

    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if attempt_no is not None:
        clauses.append("attempt_no = ?")
        params.append(attempt_no)
    if stage_id is not None:
        clauses.append("stage_id = ?")
        params.append(stage_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM qa_findings
            {where_clause}
            ORDER BY attempt_no ASC, stage_id ASC, occurred_at ASC, finding_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Backend predicate helpers (kept as thin wrappers for driver-level checks)
# ---------------------------------------------------------------------------


def backend_has_valid_context(story_dir: Path) -> bool:
    return load_story_context_row(story_dir) is not None


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return load_phase_state_row(story_dir) is not None
