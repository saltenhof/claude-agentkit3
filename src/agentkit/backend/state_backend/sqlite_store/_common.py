"""SQLite state-backend JSON projection and path helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from agentkit.backend.boundary.filesystem import atomic_write_json, load_json_object
from agentkit.backend.state_backend.config import (
    resolve_sqlite_store_root,
    versioned_sqlite_db_file,
)
from agentkit.backend.state_backend.paths import state_backend_dir

if TYPE_CHECKING:
    import sqlite3

_JsonRecord = dict[str, object]

def current_db_file_name() -> str:
    """Return the versioned SQLite database filename used by this driver."""

    return versioned_sqlite_db_file()


def state_db_path_for(story_dir: Path) -> Path:
    """Return the versioned SQLite database path used by this driver."""

    return state_backend_dir(story_dir) / current_db_file_name()


def load_json_safe(path: Path) -> _JsonRecord | None:
    """Compatibility helper for non-canonical export reads."""

    return load_json_object(path)


def _write_projection(path: Path, payload: _JsonRecord) -> None:
    """Atomically write a JSON projection file, creating parent dirs as needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


def _dump_json(data: object) -> str:
    return json.dumps(data, sort_keys=True, default=str)


def _insert_default_project(
    conn: sqlite3.Connection,
    *,
    project_key: str,
    story_id_prefix: str,
    repositories: list[str],
) -> None:
    """Insert the minimal default project row used by SQLite bootstrap paths."""

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
            story_id_prefix,
            default_configuration,
        ),
    )


def _execution_event_global_store_dir() -> Path:
    """Resolve the NEW SQLite execution-event *global* store root, fail-closed.

    AG3-094 (E9, FIX THE MODEL): the global execution-event store added by
    AG3-094 (consumed by the SSE stream and the KPI analytics source) resolves
    from the EXPLICIT configured root (``AGENTKIT_STORE_DIR`` via
    :func:`resolve_sqlite_store_root`), NOT from ``Path.cwd()`` -- that was hidden
    operational state forcing harnesses to ``os.chdir``. Fail-closed when no root
    is configured.

    This resolver is SCOPED to the new execution-event global functions
    (``append_execution_event_global_row``, ``load_execution_event_rows_global``,
    ``load_execution_event_rows_for_project_global``) which have no legacy callers.
    Pre-existing global reads (story-context / phase-state / analytics /
    story-execution-lock) keep resolving via :func:`_project_store_dir`'s
    historical ``Path.cwd()`` default -- see the scope-correction in
    ``stories/AG3-094-dashboards-live-updates-sse/jenkins-460-integration-regression.md``.

    Returns:
        The configured execution-event global store root directory.

    Raises:
        ConfigError: If ``AGENTKIT_STORE_DIR`` is unset or blank.
    """
    return Path(resolve_sqlite_store_root())


def _project_store_dir(store_dir: Path | None) -> Path:
    """Resolve a store directory; ``None`` falls back to the process CWD.

    The ``None`` (implicit/global) case resolves to ``Path.cwd()`` -- the
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


def _load_json(data: str | None, default: Any) -> Any:
    if data is None:
        return default
    return json.loads(data)


def _cast_json_record(value: object) -> _JsonRecord:
    return cast("_JsonRecord", value)
