"""Story, planning, requirements, project, and project-token row persistence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agentkit.backend.boundary.shared.time import now_iso
from agentkit.backend.exceptions import (
    CorruptStateError,
)
from agentkit.backend.state_backend.paths import (
    CONTEXT_EXPORT_FILE,
)

from ._connection import (
    _connect,
    _connect_global,
)
from ._json_projection import (
    _write_projection,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ._compat import _CompatConnection


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
        # AG3-020: the schema requires a non-empty `repositories` list, so the
        # backfill default uses [project_key] as a last-resort placeholder.
        # The mapper layer emits a WARN whenever this fallback is read.
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
            jsonb_build_object(
                'repo_url', '',
                'default_branch', 'main',
                'are_url', NULL,
                'default_worker_count', 1,
                'repositories', jsonb_build_array(?::text)
            ),
            NULL::TIMESTAMPTZ
        )
        ON CONFLICT(key) DO NOTHING
        """,
        (project_key, project_key, prefix, project_key),
    )


def _disambiguated_story_prefix(prefix: str, project_key: str) -> str:
    import hashlib

    suffix = hashlib.md5(project_key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{prefix[:4]}{suffix[:6]}".upper()


def _artifact_id_for(artifact_kind: str, attempt_no: int | None = None) -> str:
    if attempt_no is None:
        return artifact_kind.replace("_", "-")
    return f"{artifact_kind.replace('_', '-')}-attempt-{attempt_no}"


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
    """Return one story-context row by domain identity."""

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
            ORDER BY story_number ASC, story_id ASC
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
# Requirements coverage rows
# ---------------------------------------------------------------------------


def save_story_are_link_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist one StoryAreLink row.

    Migration note: ``story_are_links`` is created idempotently by
    ``_schema_create_script``. Rollback is ``DROP TABLE story_are_links`` plus
    ``DROP INDEX story_contexts_story_id_idx`` if no other table depends on it;
    no existing StoryContext rows are mutated.
    """

    del store_dir
    with _connect_global() as conn:
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

    del store_dir
    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT story_id, are_item_id, kind
            FROM story_are_links
            WHERE story_id = ?
            ORDER BY are_item_id, kind
            """,
            (story_id,),
        ).fetchall()
    return rows


def update_story_are_link_kind_row(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    old_kind: str,
    new_kind: str,
) -> dict[str, Any] | None:
    """Update one StoryAreLink kind and return the resulting row."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            UPDATE story_are_links
            SET kind = ?
            WHERE story_id = ? AND are_item_id = ? AND kind = ?
            RETURNING story_id, are_item_id, kind
            """,
            (new_kind, story_id, are_item_id, old_kind),
        ).fetchone()
    return row


def delete_story_are_link_row(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    kind: str,
) -> int:
    """Delete one StoryAreLink row and return affected row count."""

    del store_dir
    with _connect_global() as conn:
        cursor = conn.execute(
            """
            DELETE FROM story_are_links
            WHERE story_id = ? AND are_item_id = ? AND kind = ?
            """,
            (story_id, are_item_id, kind),
        )
        return int(cursor.rowcount)


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
# Project API token rows
# ---------------------------------------------------------------------------


def save_project_api_token_row(store_dir: Path | None, row: dict[str, Any]) -> None:
    """Persist a project API token row."""

    del store_dir
    with _connect_global() as conn:
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

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM project_api_tokens
            WHERE token_id = ?
            """,
            (token_id,),
        ).fetchone()
    return row


def load_project_api_token_row_by_hash(
    store_dir: Path | None,
    token_hash: str,
) -> dict[str, Any] | None:
    """Load one project API token by hash."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM project_api_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
    return row


def load_project_api_token_rows_for_project(
    store_dir: Path | None,
    project_key: str,
) -> list[dict[str, Any]]:
    """Load project API tokens for one project."""

    del store_dir
    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM project_api_tokens
            WHERE project_key = ?
            ORDER BY created_at ASC, token_id ASC
            """,
            (project_key,),
        ).fetchall()
    return rows
