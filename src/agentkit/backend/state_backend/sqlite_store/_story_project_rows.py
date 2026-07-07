"""SQLite story, planning, requirements, project, and token row persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.backend.boundary.shared.time import now_iso
from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend.config import resolve_sqlite_store_root
from agentkit.backend.state_backend.paths import CONTEXT_EXPORT_FILE

from ._common import _dump_json, _write_projection
from ._connection import _connect
from ._story_identity import _disambiguated_story_prefix, _story_id_for

if TYPE_CHECKING:
    import sqlite3


def _ensure_project_for_story_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
) -> None:
    """Ensure a project row exists for a story-context being saved.

    When a story-context references a ``project_key`` that has no matching
    project row, a minimal default project is inserted.  The
    ``repositories`` field is populated from ``row["participating_repos"]``
    when present, otherwise an empty list is stored and a WARNING is logged.

    Args:
        conn: Active SQLite connection with schema already applied.
        row: Story-context dict being saved (may contain ``participating_repos``).
    """
    import logging

    _log = logging.getLogger(__name__)

    story_id = str(row["story_id"])
    prefix = story_id.split("-", maxsplit=1)[0]
    project_key = str(row["project_key"])
    existing_project = conn.execute(
        "SELECT 1 FROM projects WHERE key = ?",
        (project_key,),
    ).fetchone()
    if existing_project is not None:
        return

    # Derive repositories from story row when possible.
    repositories: list[str] = []
    participating = row.get("participating_repos", [])
    if isinstance(participating, list) and participating:
        repositories = [str(r) for r in participating]
    else:
        _log.warning(
            "Bootstrap: project '%s' story '%s' has no participating_repos; "
            "setting repositories=[] (operator must update project configuration).",
            project_key,
            story_id,
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
                title,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, story_id) DO UPDATE SET
                story_uuid=excluded.story_uuid,
                story_number=excluded.story_number,
                story_type=excluded.story_type,
                execution_route=excluded.execution_route,
                implementation_contract=excluded.implementation_contract,
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
                title,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, story_id) DO UPDATE SET
                story_uuid=excluded.story_uuid,
                story_number=excluded.story_number,
                story_type=excluded.story_type,
                execution_route=excluded.execution_route,
                implementation_contract=excluded.implementation_contract,
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

    with _connect(_project_store_dir(store_dir)) as conn:
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


def load_story_context_rows_global(
    store_dir: Path | None,
    project_key: str,
) -> list[dict[str, Any]]:
    """Return all raw payload rows for a project's story contexts."""

    with _connect(_project_store_dir(store_dir)) as conn:
        rows = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE project_key = ?
            ORDER BY story_number ASC, story_id ASC
            """,
            (project_key,),
        ).fetchall()
    return [{"payload_json": str(row["payload_json"])} for row in rows]


def load_story_context_by_story_number_row(
    store_dir: Path | None,
    project_key: str,
    story_number: int,
) -> dict[str, Any] | None:
    """Return one story-context row by domain identity."""

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


# ---------------------------------------------------------------------------
# Execution planning rows
# ---------------------------------------------------------------------------


def save_story_dependency_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist one story dependency row.

    Migration note: ``story_dependencies`` is created idempotently by
    ``_ensure_schema``. Rollback is ``DROP TABLE story_dependencies`` plus its
    two indexes; no existing story-context data is mutated.
    """

    with _connect(_project_store_dir(store_dir)) as conn:
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

    with _connect(_project_store_dir(store_dir)) as conn:
        rows = conn.execute(
            """
            SELECT project_key, story_id, depends_on_story_id, kind, created_at
            FROM story_dependencies
            WHERE project_key = ?
            ORDER BY story_id, depends_on_story_id, kind
            """,
            (project_key,),
        ).fetchall()
    return [dict(row) for row in rows]


def load_story_dependency_rows_for_story(
    store_dir: Path | None,
    story_id: str,
) -> list[dict[str, Any]]:
    """Load direct predecessor dependency rows for one story."""

    with _connect(_project_store_dir(store_dir)) as conn:
        rows = conn.execute(
            """
            SELECT project_key, story_id, depends_on_story_id, kind, created_at
            FROM story_dependencies
            WHERE story_id = ?
            ORDER BY project_key, depends_on_story_id, kind
            """,
            (story_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_story_dependency_row(
    store_dir: Path | None,
    story_id: str,
    depends_on_story_id: str,
    kind: str,
) -> int:
    """Delete one dependency row and return affected row count."""

    with _connect(_project_store_dir(store_dir)) as conn:
        cursor = conn.execute(
            """
            DELETE FROM story_dependencies
            WHERE story_id = ? AND depends_on_story_id = ? AND kind = ?
            """,
            (story_id, depends_on_story_id, kind),
        )
        return cursor.rowcount


def save_parallelization_config_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist one parallelization config row."""

    with _connect(_project_store_dir(store_dir)) as conn:
        conn.execute(
            """
            INSERT INTO parallelization_configs (
                project_key,
                max_parallel_stories,
                max_parallel_stories_per_repo,
                extra_config_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_key) DO UPDATE SET
                max_parallel_stories = excluded.max_parallel_stories,
                max_parallel_stories_per_repo =
                    excluded.max_parallel_stories_per_repo,
                extra_config_json = excluded.extra_config_json,
                updated_at = excluded.updated_at
            """,
            (
                row["project_key"],
                row["max_parallel_stories"],
                row["max_parallel_stories_per_repo"],
                row["extra_config_json"],
                now_iso(),
            ),
        )


def load_parallelization_config_row(
    store_dir: Path | None,
    project_key: str,
) -> dict[str, Any] | None:
    """Load one parallelization config row."""

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT
                project_key,
                max_parallel_stories,
                max_parallel_stories_per_repo,
                extra_config_json
            FROM parallelization_configs
            WHERE project_key = ?
            """,
            (project_key,),
        ).fetchone()
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Requirements coverage rows
# ---------------------------------------------------------------------------


def save_story_are_link_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist one StoryAreLink row.

    Migration note: ``story_are_links`` is created idempotently by
    ``_ensure_schema``. Rollback is ``DROP TABLE story_are_links`` plus the
    optional ``story_contexts_story_id_idx`` index if no other table uses it;
    no existing StoryContext rows are mutated.
    """

    with _connect(_project_store_dir(store_dir)) as conn:
        conn.execute(
            """
            INSERT INTO story_are_links (
                story_id,
                are_item_id,
                kind
            ) VALUES (?, ?, ?)
            """,
            (
                row["story_id"],
                row["are_item_id"],
                row["kind"],
            ),
        )


def load_story_are_link_rows(
    store_dir: Path | None,
    story_id: str,
) -> list[dict[str, Any]]:
    """Load StoryAreLink rows for one story."""

    with _connect(_project_store_dir(store_dir)) as conn:
        rows = conn.execute(
            """
            SELECT story_id, are_item_id, kind
            FROM story_are_links
            WHERE story_id = ?
            ORDER BY are_item_id, kind
            """,
            (story_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_story_are_link_kind_row(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    old_kind: str,
    new_kind: str,
) -> dict[str, Any] | None:
    """Update one StoryAreLink kind and return the resulting row."""

    with _connect(_project_store_dir(store_dir)) as conn:
        cursor = conn.execute(
            """
            UPDATE story_are_links
            SET kind = ?
            WHERE story_id = ? AND are_item_id = ? AND kind = ?
            """,
            (new_kind, story_id, are_item_id, old_kind),
        )
        if cursor.rowcount == 0:
            return None
        row = conn.execute(
            """
            SELECT story_id, are_item_id, kind
            FROM story_are_links
            WHERE story_id = ? AND are_item_id = ? AND kind = ?
            """,
            (story_id, are_item_id, new_kind),
        ).fetchone()
    return dict(row) if row is not None else None


def delete_story_are_link_row(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    kind: str,
) -> int:
    """Delete one StoryAreLink row and return affected row count."""

    with _connect(_project_store_dir(store_dir)) as conn:
        cursor = conn.execute(
            """
            DELETE FROM story_are_links
            WHERE story_id = ? AND are_item_id = ? AND kind = ?
            """,
            (story_id, are_item_id, kind),
        )
        return cursor.rowcount


# ---------------------------------------------------------------------------
# Project rows
# ---------------------------------------------------------------------------


def _execution_event_global_store_dir() -> Path:
    """Resolve the NEW SQLite execution-event *global* store root, fail-closed.

    AG3-094 (E9, FIX THE MODEL): the global execution-event store added by
    AG3-094 (consumed by the SSE stream and the KPI analytics source) resolves
    from the EXPLICIT configured root (``AGENTKIT_STORE_DIR`` via
    :func:`resolve_sqlite_store_root`), NOT from ``Path.cwd()`` — that was hidden
    operational state forcing harnesses to ``os.chdir``. Fail-closed when no root
    is configured.

    This resolver is SCOPED to the new execution-event global functions
    (``append_execution_event_global_row``, ``load_execution_event_rows_global``,
    ``load_execution_event_rows_for_project_global``) which have no legacy callers.
    Pre-existing global reads (story-context / phase-state / analytics /
    story-execution-lock) keep resolving via :func:`_project_store_dir`'s
    historical ``Path.cwd()`` default — see the scope-correction in
    ``stories/AG3-094-dashboards-live-updates-sse/jenkins-460-integration-regression.md``.

    Returns:
        The configured execution-event global store root directory.

    Raises:
        ConfigError: If ``AGENTKIT_STORE_DIR`` is unset or blank.
    """
    return Path(resolve_sqlite_store_root())


def _project_store_dir(store_dir: Path | None) -> Path:
    """Resolve a store directory; ``None`` falls back to the process CWD.

    The ``None`` (implicit/global) case resolves to ``Path.cwd()`` — the
    historical pre-AG3-094 behavior for the pre-existing global reads
    (story-context, phase-state, analytics, story-execution-lock). AG3-094's
    fail-closed explicit-root resolution is intentionally scoped to the NEW
    execution-event global store only (:func:`_execution_event_global_store_dir`);
    broadening it to every global read is deferred to its own backend story (see
    the AG3-094 jenkins-460 scope-correction note).
    """
    if store_dir is None:
        return Path.cwd()
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
# Project API token rows
# ---------------------------------------------------------------------------


def save_project_api_token_row(store_dir: Path | None, row: dict[str, Any]) -> None:
    """Persist a project API token row."""

    with _connect(_project_store_dir(store_dir)) as conn:
        conn.execute(
            """
            INSERT INTO project_api_tokens (
                token_id,
                project_key,
                label,
                token_hash,
                created_at,
                revoked_at,
                last_used_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(token_id) DO UPDATE SET
                label = excluded.label,
                token_hash = excluded.token_hash,
                revoked_at = excluded.revoked_at,
                last_used_at = excluded.last_used_at
            """,
            (
                row["token_id"],
                row["project_key"],
                row["label"],
                row["token_hash"],
                row["created_at"],
                row["revoked_at"],
                row["last_used_at"],
            ),
        )


def load_project_api_token_row(
    store_dir: Path | None,
    token_id: str,
) -> dict[str, Any] | None:
    """Load one project API token by id."""

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM project_api_tokens
            WHERE token_id = ?
            """,
            (token_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def load_project_api_token_row_by_hash(
    store_dir: Path | None,
    token_hash: str,
) -> dict[str, Any] | None:
    """Load one project API token by hash."""

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM project_api_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
    return dict(row) if row is not None else None


def load_project_api_token_rows_for_project(
    store_dir: Path | None,
    project_key: str,
) -> list[dict[str, Any]]:
    """Load project API tokens for one project."""

    with _connect(_project_store_dir(store_dir)) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM project_api_tokens
            WHERE project_key = ?
            ORDER BY created_at ASC, token_id ASC
            """,
            (project_key,),
        ).fetchall()
    return [dict(row) for row in rows]
