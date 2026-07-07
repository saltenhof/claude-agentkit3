"""SQLite story-execution lock row persistence."""

from __future__ import annotations

from typing import Any

from ._connection import _connect
from ._story_project_rows import _project_store_dir


def save_story_execution_lock_global_row(row: dict[str, Any]) -> None:
    """Persist a story-execution-lock row dict globally.

    AG3-031 Pass-7: SQLite path symmetric with postgres_store.
    Table DDL is bootstrapped via ``_ensure_schema_runtime_tables``.
    Uses ``_project_store_dir(None)`` (= ``Path.cwd()``) as the global
    store location, consistent with all other ``*_global_row`` functions.
    """

    with _connect(_project_store_dir(None)) as conn:
        conn.execute(
            """
            INSERT INTO story_execution_locks (
                project_key, story_id, run_id, lock_type, status,
                worktree_roots_json, binding_version, activated_at,
                updated_at, deactivated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (project_key, story_id, run_id, lock_type) DO UPDATE SET
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
    """Return the raw story-execution-lock row, or None.

    AG3-031 Pass-7: SQLite path symmetric with postgres_store.
    Uses ``_project_store_dir(None)`` (= ``Path.cwd()``) as the global
    store location.
    """

    with _connect(_project_store_dir(None)) as conn:
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
