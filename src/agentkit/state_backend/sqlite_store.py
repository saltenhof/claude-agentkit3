"""SQLite-backed canonical runtime store with JSON projections.

This module is a T-bloodtype infrastructure driver.
It MUST NOT import BC-Records (A-bloodtype components).
All BC-Record <-> dict conversions live in
``agentkit.state_backend.store.mappers`` (boundary.state_backend_repository).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from agentkit.boundary.filesystem import atomic_write_json, load_json_object
from agentkit.boundary.shared.time import now_iso
from agentkit.exceptions import CorruptStateError
from agentkit.state_backend.paths import (
    CLOSURE_REPORT_FILE,
    CONTEXT_EXPORT_FILE,
    PHASE_STATE_EXPORT_FILE,
    VERIFY_DECISION_FILE,
    state_db_path,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentkit.state_backend.scope import RuntimeStateScope

_JsonRecord = dict[str, object]


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


@contextmanager
def _connect(story_dir: Path) -> Iterator[sqlite3.Connection]:
    db_path = state_db_path(story_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS story_contexts (
            story_uuid TEXT NOT NULL,
            project_key TEXT NOT NULL,
            story_number INTEGER NOT NULL,
            story_id TEXT NOT NULL,
            story_type TEXT NOT NULL,
            execution_route TEXT NOT NULL,
            implementation_contract TEXT,
            issue_nr INTEGER,
            title TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id),
            FOREIGN KEY (project_key) REFERENCES projects(key)
        );

        CREATE TABLE IF NOT EXISTS projects (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            story_id_prefix TEXT NOT NULL UNIQUE,
            configuration_json TEXT NOT NULL,
            archived_at TEXT
        );

        CREATE INDEX IF NOT EXISTS projects_archived_at_idx
            ON projects (archived_at);

        CREATE TABLE IF NOT EXISTS story_number_counters (
            project_key TEXT PRIMARY KEY,
            next_story_number INTEGER NOT NULL,
            FOREIGN KEY (project_key) REFERENCES projects(key)
        );

        CREATE TABLE IF NOT EXISTS phase_states (
            story_id TEXT PRIMARY KEY,
            phase TEXT NOT NULL,
            status TEXT NOT NULL,
            paused_reason TEXT,
            review_round INTEGER NOT NULL,
            attempt_id TEXT,
            errors_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS phase_snapshots (
            story_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            status TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (story_id, phase)
        );

        CREATE TABLE IF NOT EXISTS attempt_records (
            story_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            seq INTEGER NOT NULL,
            attempt_id TEXT NOT NULL,
            entered_at TEXT NOT NULL,
            exit_status TEXT,
            outcome TEXT,
            yield_status TEXT,
            resume_trigger TEXT,
            guard_evaluations_json TEXT NOT NULL,
            artifacts_json TEXT NOT NULL,
            PRIMARY KEY (story_id, phase, seq)
        );

        CREATE TABLE IF NOT EXISTS flow_executions (
            story_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            run_id TEXT NOT NULL,
            flow_id TEXT NOT NULL,
            level TEXT NOT NULL,
            owner TEXT NOT NULL,
            parent_flow_id TEXT,
            status TEXT NOT NULL,
            current_node_id TEXT,
            attempt_no INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS node_execution_ledgers (
            story_id TEXT NOT NULL,
            flow_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            project_key TEXT NOT NULL,
            run_id TEXT NOT NULL,
            execution_count INTEGER NOT NULL,
            success_count INTEGER NOT NULL,
            last_outcome TEXT,
            last_attempt_no INTEGER,
            last_executed_at TEXT,
            PRIMARY KEY (story_id, flow_id, node_id)
        );

        CREATE TABLE IF NOT EXISTS execution_events (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            source_component TEXT NOT NULL,
            severity TEXT NOT NULL,
            phase TEXT,
            flow_id TEXT,
            node_id TEXT,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id, event_id)
        );

        CREATE TABLE IF NOT EXISTS story_metrics (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            story_type TEXT NOT NULL,
            story_size TEXT NOT NULL,
            mode TEXT NOT NULL,
            processing_time_min REAL NOT NULL,
            qa_rounds INTEGER NOT NULL,
            increments INTEGER NOT NULL,
            final_status TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            adversarial_findings INTEGER,
            adversarial_tests_created INTEGER,
            files_changed INTEGER,
            agentkit_version TEXT,
            agentkit_commit TEXT,
            config_version TEXT,
            llm_roles_json TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id)
        );

        CREATE TABLE IF NOT EXISTS override_records (
            override_id TEXT PRIMARY KEY,
            story_id TEXT NOT NULL,
            project_key TEXT NOT NULL,
            run_id TEXT NOT NULL,
            flow_id TEXT NOT NULL,
            target_node_id TEXT,
            override_type TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            consumed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS artifact_records (
            story_id TEXT NOT NULL,
            artifact_kind TEXT NOT NULL,
            artifact_name TEXT NOT NULL,
            producer TEXT NOT NULL,
            status TEXT,
            attempt_nr INTEGER,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (story_id, artifact_kind, artifact_name, attempt_nr)
        );

        CREATE TABLE IF NOT EXISTS decision_records (
            story_id TEXT NOT NULL,
            decision_kind TEXT NOT NULL,
            attempt_nr INTEGER NOT NULL,
            status TEXT NOT NULL,
            passed INTEGER NOT NULL,
            summary TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (story_id, decision_kind, attempt_nr)
        );
        """
    )
    _ensure_story_identity_migration(conn)


def _ensure_story_identity_migration(conn: sqlite3.Connection) -> None:
    """Apply idempotent story-identity schema migration.

    Rollback plan: drop ``story_contexts_story_uuid_idx``,
    ``story_contexts_project_story_number_idx`` and
    ``story_number_counters``; keep ``story_id`` and ``payload_json`` as the
    legacy source of truth. The migration only adds columns/indexes and
    backfills values from materialized ``story_id``.
    """

    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(story_contexts)").fetchall()
    }
    if "story_uuid" not in columns:
        conn.execute("ALTER TABLE story_contexts ADD COLUMN story_uuid TEXT")
    if "story_number" not in columns:
        conn.execute("ALTER TABLE story_contexts ADD COLUMN story_number INTEGER")

    for row in conn.execute(
        "SELECT project_key, story_id FROM story_contexts WHERE story_uuid IS NULL",
    ).fetchall():
        conn.execute(
            """
            UPDATE story_contexts
            SET story_uuid = ?
            WHERE project_key = ? AND story_id = ?
            """,
            (str(uuid4()), row["project_key"], row["story_id"]),
        )

    for row in conn.execute(
        "SELECT project_key, story_id FROM story_contexts WHERE story_number IS NULL",
    ).fetchall():
        story_number = _story_number_from_id(str(row["story_id"]))
        if story_number is None:
            continue
        conn.execute(
            """
            UPDATE story_contexts
            SET story_number = ?
            WHERE project_key = ? AND story_id = ?
            """,
            (story_number, row["project_key"], row["story_id"]),
        )

    _ensure_default_projects_for_story_contexts(conn)
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_story_uuid_idx
            ON story_contexts (story_uuid)
        """,
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_project_story_number_idx
            ON story_contexts (project_key, story_number)
        """,
    )
    conn.execute(
        """
        INSERT INTO story_number_counters (project_key, next_story_number)
        SELECT project_key, COALESCE(MAX(story_number), 0) + 1
        FROM story_contexts
        WHERE story_number IS NOT NULL
        GROUP BY project_key
        ON CONFLICT(project_key) DO UPDATE SET
            next_story_number = MAX(
                story_number_counters.next_story_number,
                excluded.next_story_number
            )
        """,
    )


def _ensure_default_projects_for_story_contexts(conn: sqlite3.Connection) -> None:
    default_configuration = _dump_json(
        {
            "repo_url": "",
            "default_branch": "main",
            "are_url": None,
            "default_worker_count": 1,
        },
    )
    rows = conn.execute(
        """
        SELECT DISTINCT sc.project_key, sc.story_id
        FROM story_contexts sc
        LEFT JOIN projects p ON p.key = sc.project_key
        WHERE p.key IS NULL
        """,
    ).fetchall()
    for row in rows:
        prefix = str(row["story_id"]).split("-", maxsplit=1)[0]
        conn.execute(
            """
            INSERT OR IGNORE INTO projects (
                key,
                name,
                story_id_prefix,
                configuration_json,
                archived_at
            )
            VALUES (?, ?, ?, ?, NULL)
            """,
            (
                row["project_key"],
                row["project_key"],
                prefix,
                default_configuration,
            ),
        )


def _ensure_project_for_story_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
) -> None:
    default_configuration = _dump_json(
        {
            "repo_url": "",
            "default_branch": "main",
            "are_url": None,
            "default_worker_count": 1,
        },
    )
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
        INSERT OR IGNORE INTO projects (
            key,
            name,
            story_id_prefix,
            configuration_json,
            archived_at
        )
        VALUES (?, ?, ?, ?, NULL)
        """,
        (
            project_key,
            project_key,
            prefix,
            default_configuration,
        ),
    )


def _disambiguated_story_prefix(prefix: str, project_key: str) -> str:
    suffix = "".join(ch for ch in project_key.upper() if ch.isalnum())[:6]
    if not suffix:
        suffix = "X"
    return f"{prefix[: max(1, 10 - len(suffix))]}{suffix}"[:10]


def _story_number_from_id(story_id: str) -> int | None:
    suffix = story_id.rsplit("-", maxsplit=1)[-1]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _story_id_for(story_dir: Path) -> str | None:
    return story_dir.name or None


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

    with _connect(_project_store_dir(store_dir)) as conn:
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
    project_key: str,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the raw payload row for a global story context, or None."""

    with _connect(Path.cwd()) as conn:
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

    with _connect(_project_store_dir(store_dir)) as conn:
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

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE story_uuid = ?
            """,
            (story_uuid,),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def allocate_next_story_number_row(store_dir: Path | None, project_key: str) -> int:
    """Atomically reserve the next story number for one project."""

    with _connect(_project_store_dir(store_dir)) as conn:
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT next_story_number
            FROM story_number_counters
            WHERE project_key = ?
            """,
            (project_key,),
        ).fetchone()
        if row is None:
            max_row = conn.execute(
                """
                SELECT COALESCE(MAX(story_number), 0) + 1 AS next_story_number
                FROM story_contexts
                WHERE project_key = ?
                """,
                (project_key,),
            ).fetchone()
            next_story_number = int(max_row["next_story_number"])
            conn.execute(
                """
                INSERT INTO story_number_counters (project_key, next_story_number)
                VALUES (?, ?)
                """,
                (project_key, next_story_number + 1),
            )
            return next_story_number

        next_story_number = int(row["next_story_number"])
        conn.execute(
            """
            UPDATE story_number_counters
            SET next_story_number = ?
            WHERE project_key = ?
            """,
            (next_story_number + 1, project_key),
        )
        return next_story_number


# ---------------------------------------------------------------------------
# Project rows
# ---------------------------------------------------------------------------


def _project_store_dir(store_dir: Path | None) -> Path:
    if store_dir is None:
        from pathlib import Path as _Path

        return _Path.cwd()
    return store_dir


def save_project_row(store_dir: Path | None, row: dict[str, Any]) -> None:
    """Persist a project row."""

    with _connect(_project_store_dir(store_dir)) as conn:
        conn.execute(
            """
            INSERT INTO projects (
                key,
                name,
                story_id_prefix,
                configuration_json,
                archived_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                name = excluded.name,
                configuration_json = excluded.configuration_json,
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

    with _connect(_project_store_dir(store_dir)) as conn:
        found = conn.execute(
            """
            SELECT
                key,
                name,
                story_id_prefix,
                configuration_json,
                archived_at
            FROM projects
            WHERE key = ?
            """,
            (key,),
        ).fetchone()
    return dict(found) if found is not None else None


def load_project_row_by_story_id_prefix(
    store_dir: Path | None,
    story_id_prefix: str,
) -> dict[str, Any] | None:
    """Load one project row by story-id prefix."""

    with _connect(_project_store_dir(store_dir)) as conn:
        found = conn.execute(
            """
            SELECT
                key,
                name,
                story_id_prefix,
                configuration_json,
                archived_at
            FROM projects
            WHERE story_id_prefix = ?
            """,
            (story_id_prefix,),
        ).fetchone()
    return dict(found) if found is not None else None


def load_project_rows(
    store_dir: Path | None,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Load project rows."""

    query = """
        SELECT
            key,
            name,
            story_id_prefix,
            configuration_json,
            archived_at
        FROM projects
        ORDER BY key
        """
    params: tuple[object, ...] = ()
    if not include_archived:
        query = """
            SELECT
                key,
                name,
                story_id_prefix,
                configuration_json,
                archived_at
            FROM projects
            WHERE archived_at IS NULL
            ORDER BY key
            """
    with _connect(_project_store_dir(store_dir)) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


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


# ---------------------------------------------------------------------------
# ExecutionEventRecord rows
# ---------------------------------------------------------------------------


def append_execution_event_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist an execution-event row dict to the database."""

    with _connect(story_dir) as conn:
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


def append_execution_event_global_row(row: dict[str, Any]) -> None:
    """Global execution-event append is unsupported on SQLite."""

    del row
    raise RuntimeError(
        "Global execution-event append requires the postgres state backend",
    )


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
        clauses.append("project_key = ?")
        params.append(project_key)
    if story_id is not None:
        clauses.append("story_id = ?")
        params.append(story_id)
    if run_id is not None:
        clauses.append("run_id = ?")
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
        clauses.append("project_key = ?")
        params.append(project_key)
    if story_id is not None:
        clauses.append("story_id = ?")
        params.append(story_id)
    if run_id is not None:
        clauses.append("run_id = ?")
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
# QA layer artifacts + verify decision
# ---------------------------------------------------------------------------

_ARTIFACT_PRODUCERS: dict[str, str] = {
    "structural": "qa-structural-check",
    "semantic": "qa-semantic-review",
    "adversarial": "qa-adversarial",
}


def persist_layer_artifact_rows(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    layer_payload_rows: list[dict[str, object]],
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist QA layer artifact rows and write projection files.

    ``layer_payload_rows`` contains pre-serialized dicts from the mapper layer.
    Each element has keys: ``layer``, ``artifact_name``, ``producer_component``,
    ``payload``, ``passed``, ``recorded_at``.
    ``flow_row`` and FK-69 fields (``stage_row``, ``finding_rows``) are
    ignored on SQLite (FK-69 read models are Postgres-only).
    """
    del flow_row
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist QA layer artifacts without story context "
            "in canonical backend",
        )
    produced: list[str] = []
    with _connect(story_dir) as conn:
        for item in layer_payload_rows:
            layer = str(item["layer"])
            artifact_name = str(item["artifact_name"])
            payload = cast("_JsonRecord", item["payload"])
            passed = bool(item["passed"])
            target_dir = projection_dir or story_dir
            _write_projection(target_dir / artifact_name, payload)
            conn.execute(
                """
                INSERT INTO artifact_records (
                    story_id, artifact_kind, artifact_name, producer,
                    status, attempt_nr, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(story_id, artifact_kind, artifact_name, attempt_nr)
                DO UPDATE SET
                    producer=excluded.producer,
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    created_at=excluded.created_at
                """,
                (
                    story_id,
                    layer,
                    artifact_name,
                    _ARTIFACT_PRODUCERS.get(layer, "qa-layer"),
                    "PASS" if passed else "FAIL",
                    attempt_nr,
                    _dump_json(payload),
                    now_iso(),
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

    del flow_row
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist verify decision without story context in canonical backend",
        )
    target_dir = projection_dir or story_dir
    _write_projection(target_dir / VERIFY_DECISION_FILE, canonical_payload)
    written = (VERIFY_DECISION_FILE,)
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO decision_records (
                story_id, decision_kind, attempt_nr, status, passed,
                summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id, decision_kind, attempt_nr) DO UPDATE SET
                status=excluded.status,
                passed=excluded.passed,
                summary=excluded.summary,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                story_id,
                "verify",
                attempt_nr,
                decision_row["status"],
                1 if decision_row["passed"] else 0,
                decision_row["summary"],
                _dump_json(canonical_payload),
                now_iso(),
            ),
        )
        conn.execute(
            """
            INSERT INTO artifact_records (
                story_id, artifact_kind, artifact_name, producer,
                status, attempt_nr, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id, artifact_kind, artifact_name, attempt_nr)
            DO UPDATE SET
                producer=excluded.producer,
                status=excluded.status,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                story_id,
                "verify_decision",
                written[0],
                "qa-policy-engine",
                decision_row["status"],
                attempt_nr,
                _dump_json(canonical_payload),
                now_iso(),
            ),
        )
    return written


def load_latest_verify_decision_payload(
    story_dir: Path,
) -> dict[str, object] | None:
    """Return the latest verify-decision payload dict, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
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
            f"decision_records payload is invalid in {state_db_path(story_dir)}: {exc}",
        ) from exc


def load_latest_verify_decision_payload_for_scope(
    scope: RuntimeStateScope,
) -> dict[str, object] | None:
    """Return the latest verify-decision payload for a scope, or None."""

    return load_latest_verify_decision_payload(scope.story_dir)


def load_artifact_record_payload(
    story_dir: Path,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Return the latest artifact payload dict for a kind, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
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
            f"artifact_records payload is invalid in {state_db_path(story_dir)}: {exc}",
        ) from exc


def load_artifact_record_payload_for_scope(
    scope: RuntimeStateScope,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Return the latest artifact payload dict for a scope and kind, or None."""

    return load_artifact_record_payload(scope.story_dir, artifact_kind)


def persist_closure_report_row(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    report_row: dict[str, Any],
    projection_dir: Path | None = None,
) -> Path:
    """Persist a closure-report and write the projection file."""

    del flow_row
    story_id = _story_id_for(story_dir) or str(report_row["story_id"])
    target_dir = projection_dir or story_dir
    path = target_dir / CLOSURE_REPORT_FILE
    payload = cast("_JsonRecord", report_row["payload"])
    _write_projection(path, payload)
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO artifact_records (
                story_id, artifact_kind, artifact_name, producer,
                status, attempt_nr, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id, artifact_kind, artifact_name, attempt_nr)
            DO UPDATE SET
                producer=excluded.producer,
                status=excluded.status,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                story_id,
                "closure_report",
                path.name,
                "closure-phase",
                str(report_row["status"]).upper(),
                0,
                _dump_json(payload),
                now_iso(),
            ),
        )
    return path


# ---------------------------------------------------------------------------
# QA read models (SQLite: Postgres-only, raise RuntimeError)
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
    """FK-69 QA read models are only materialized on the Postgres backend."""

    del story_dir, project_key, story_id, run_id, attempt_no, stage_id
    raise RuntimeError(
        "FK-69 QA read models are only materialized on the Postgres backend. "
        "SQLite remains a narrow unit-test backend.",
    )


def load_qa_finding_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[dict[str, Any]]:
    """FK-69 QA read models are only materialized on the Postgres backend."""

    del story_dir, project_key, story_id, run_id, attempt_no, stage_id
    raise RuntimeError(
        "FK-69 QA read models are only materialized on the Postgres backend. "
        "SQLite remains a narrow unit-test backend.",
    )


# ---------------------------------------------------------------------------
# Backend predicate helpers (kept as thin wrappers for driver-level checks)
# ---------------------------------------------------------------------------


def backend_has_valid_context(story_dir: Path) -> bool:
    return load_story_context_row(story_dir) is not None


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return load_phase_state_row(story_dir) is not None
