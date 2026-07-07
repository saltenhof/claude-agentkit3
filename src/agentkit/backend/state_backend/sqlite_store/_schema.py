"""SQLite base schema bootstrap and idempotent migrations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from ._common import _dump_json
from ._schema_runtime import _ensure_schema_runtime_tables
from ._story_identity import _story_number_from_id

if TYPE_CHECKING:
    import sqlite3


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS story_contexts (
            story_uuid TEXT NOT NULL,
            project_key TEXT NOT NULL,
            story_number INTEGER NOT NULL,
            story_id TEXT NOT NULL,
            story_type TEXT NOT NULL,
            -- execution_route is nullable since AG3-021: non-implementing
            -- story types (concept/research) carry NULL instead of a
            -- sentinel value (see AG3-021 §2.1.1.1 StoryMode values).
            execution_route TEXT,
            implementation_contract TEXT,
            title TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id),
            FOREIGN KEY (project_key) REFERENCES projects(key)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_story_id_idx
            ON story_contexts (story_id);

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

        -- AG3-050 (FK-02 §2.11.3, FK-18 §18.6a/§18.13): the StoryDependency edge
        -- binds to the STATIC story stammdaten (`stories`), NOT the runtime
        -- projection (`story_contexts`). story_id/depends_on_story_id hold
        -- display-ID strings, so the FK target columns are display-ID columns.
        -- A3: the FK is COMPOSITE on (project_key, story_id) ->
        -- stories(project_key, story_display_id) for BOTH endpoints, so an edge
        -- whose endpoints live in a different project is rejected fail-closed at
        -- the FK (not merely "display-ID exists somewhere"). story_display_id is
        -- chosen over story_uuid because the columns carry display-ID strings
        -- (no wire/data change), and over story_number because that would force
        -- storing numbers instead of the display ID.
        CREATE TABLE IF NOT EXISTS story_dependencies (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            depends_on_story_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id, depends_on_story_id, kind),
            FOREIGN KEY (project_key) REFERENCES projects(key),
            FOREIGN KEY (project_key, story_id)
                REFERENCES stories(project_key, story_display_id),
            FOREIGN KEY (project_key, depends_on_story_id)
                REFERENCES stories(project_key, story_display_id)
        );

        CREATE INDEX IF NOT EXISTS story_dependencies_project_story_idx
            ON story_dependencies (project_key, story_id);

        CREATE INDEX IF NOT EXISTS story_dependencies_project_depends_idx
            ON story_dependencies (project_key, depends_on_story_id);

        CREATE TABLE IF NOT EXISTS parallelization_configs (
            project_key TEXT PRIMARY KEY,
            max_parallel_stories INTEGER NOT NULL,
            max_parallel_stories_per_repo INTEGER,
            extra_config_json TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_key) REFERENCES projects(key)
        );

        CREATE TABLE IF NOT EXISTS story_are_links (
            story_id TEXT NOT NULL,
            are_item_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            PRIMARY KEY (story_id, are_item_id, kind),
            FOREIGN KEY (story_id) REFERENCES story_contexts(story_id)
        );

        CREATE TABLE IF NOT EXISTS project_api_tokens (
            token_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            label TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            revoked_at TEXT,
            last_used_at TEXT,
            FOREIGN KEY (project_key) REFERENCES projects(key)
        );

        CREATE INDEX IF NOT EXISTS project_api_tokens_project_idx
            ON project_api_tokens (project_key);

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
        """
    )
    _ensure_schema_runtime_tables(conn)
    _ensure_story_identity_migration(conn)
    _ensure_four_phase_migration(conn)


def _ensure_story_identity_migration(conn: sqlite3.Connection) -> None:
    """Apply idempotent story-identity schema migration.

    Rollback plan: drop ``story_contexts_story_uuid_idx``,
    ``story_contexts_project_story_number_idx`` and
    ``story_number_counters``; keep ``story_id`` and ``payload_json`` as the
    legacy source of truth. The migration only adds columns/indexes and
    backfills values from materialized ``story_id``.
    """

    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(story_contexts)").fetchall()}
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


def _ensure_four_phase_migration(conn: sqlite3.Connection) -> None:
    """Map legacy top-level verify phase records into implementation.

    Idempotent migration for the four-phase model. Existing implementation
    records win on key collisions; duplicate legacy verify records are removed
    after the safe update path. Rollback plan: restore from backup or rename
    affected implementation rows back to verify before starting a four-phase
    runtime.
    """

    conn.execute(
        """
        UPDATE phase_states
        SET phase = 'implementation'
        WHERE phase = 'verify'
        """,
    )
    conn.execute(
        """
        UPDATE flow_executions
        SET current_node_id = 'implementation'
        WHERE current_node_id = 'verify'
        """,
    )
    conn.execute(
        """
        UPDATE node_execution_ledgers
        SET node_id = 'implementation'
        WHERE node_id = 'verify'
          AND NOT EXISTS (
              SELECT 1 FROM node_execution_ledgers existing
              WHERE existing.story_id = node_execution_ledgers.story_id
                AND existing.flow_id = node_execution_ledgers.flow_id
                AND existing.node_id = 'implementation'
          )
        """,
    )
    conn.execute(
        """
        DELETE FROM node_execution_ledgers
        WHERE node_id = 'verify'
        """,
    )
    conn.execute(
        """
        UPDATE phase_snapshots
        SET phase = 'implementation'
        WHERE phase = 'verify'
          AND NOT EXISTS (
              SELECT 1 FROM phase_snapshots existing
              WHERE existing.story_id = phase_snapshots.story_id
                AND existing.phase = 'implementation'
          )
        """,
    )
    conn.execute(
        """
        DELETE FROM phase_snapshots
        WHERE phase = 'verify'
        """,
    )
    # The legacy ``attempt_records`` table was removed with schema 3.5.0
    # (see AG3-025 re-review finding 2): no more migration updates
    # on the old table. ``attempts`` is the new source and is
    # not touched by the 'verify' -> 'implementation' consolidation.


def _ensure_default_projects_for_story_contexts(conn: sqlite3.Connection) -> None:
    """Ensure every orphaned story_context has a parent project row.

    This migration-helper runs during schema bootstrap.  For each
    ``story_context`` that has no matching ``projects`` row, a minimal
    default project is inserted.

    The ``repositories`` field introduced by AG3-020 is derived from
    ``participating_repos`` in the story-context payload when available.
    When the payload carries no usable list, ``[project_key]`` is used as
    a last-resort placeholder so the strict ``ProjectConfiguration`` schema
    (``repositories: list[str] = Field(min_length=1)``) does not reject the
    row on read.  The mapper layer emits a WARN whenever this fallback is
    encountered so the operator can replace it.
    """
    import logging

    _log = logging.getLogger(__name__)

    rows = conn.execute(
        """
        SELECT DISTINCT sc.project_key, sc.story_id, sc.payload_json
        FROM story_contexts sc
        LEFT JOIN projects p ON p.key = sc.project_key
        WHERE p.key IS NULL
        """,
    ).fetchall()
    for row in rows:
        prefix = str(row["story_id"]).split("-", maxsplit=1)[0]
        project_key = str(row["project_key"])

        # Derive repositories from story-context payload when possible.
        repositories: list[str] = []
        try:
            import json as _json

            payload = _json.loads(str(row["payload_json"] or "{}"))
            participating = payload.get("participating_repos", [])
            if isinstance(participating, list) and participating:
                repositories = [str(r) for r in participating]
        except Exception:  # noqa: BLE001
            pass

        if not repositories:
            # Strict schema rejects []; fall back to [project_key] so the
            # default project is at least readable.  Mapper logs WARN.
            repositories = [project_key]
            _log.warning(
                "Bootstrap: project '%s' has no participating_repos in "
                "story_context payload; falling back to repositories=[%r] "
                "(operator MUST replace this placeholder).",
                project_key,
                project_key,
            )

        default_configuration = _dump_json(
            {
                "repo_url": "",
                "default_branch": "main",
                "are_url": None,
                "default_worker_count": 1,
                "repositories": repositories,
            },
        )

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
