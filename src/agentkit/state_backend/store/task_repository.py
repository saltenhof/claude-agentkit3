"""State-backend repository for task-management tables."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from agentkit.state_backend.store.projection_repositories import (
    _is_postgres,
    _postgres_connect,
    _sqlite_connect_qa,
)
from agentkit.task_management.models import (
    ResolvedBy,
    Task,
    TaskKind,
    TaskLink,
    TaskListFilter,
    TaskOrigin,
    TaskPriority,
    TaskStatus,
    TaskTargetKind,
)

if TYPE_CHECKING:
    from pathlib import Path


@runtime_checkable
class TaskRepository(Protocol):
    """Read/write repository for ``tm_tasks`` and ``tm_task_links``."""

    def write_task(self, task: Task) -> None:
        """Persist a task row."""
        ...

    def get_task(self, project_key: str, task_id: str) -> Task | None:
        """Load one task by project-scoped identity."""
        ...

    def list_tasks(
        self,
        project_key: str,
        *,
        filter: TaskListFilter | None = None,  # noqa: A002
    ) -> list[Task]:
        """Load project-scoped tasks with optional filters."""
        ...

    def write_task_link(self, link: TaskLink) -> None:
        """Persist a task-link row."""
        ...

    def delete_task_link(self, link: TaskLink) -> bool:
        """Delete a task-link row and return whether a row was removed."""
        ...

    def list_tasks_for_target(
        self,
        project_key: str,
        target_kind: TaskTargetKind,
        target_id: str,
    ) -> list[Task]:
        """Load tasks linked to a project-scoped target."""
        ...

    def story_target_exists(self, project_key: str, story_id: str) -> bool:
        """Return whether the canonical story identity exists."""
        ...


def _task_to_row(task: Task) -> dict[str, object]:
    return {
        "project_key": task.project_key,
        "task_id": task.task_id,
        "kind": task.kind.value,
        "type": task.type,
        "title": task.title,
        "body": task.body,
        "priority": task.priority.value,
        "status": task.status.value,
        "origin": task.origin.value,
        "source_story_id": task.source_story_id,
        "execution_report_ref": task.execution_report_ref,
        "created_at": task.created_at.isoformat(),
        "resolved_at": task.resolved_at.isoformat() if task.resolved_at else None,
        "resolved_by": task.resolved_by.value if task.resolved_by else None,
    }


def _link_to_row(link: TaskLink) -> dict[str, object]:
    return {
        "project_key": link.project_key,
        "task_id": link.task_id,
        "target_kind": link.target_kind.value,
        "target_id": link.target_id,
        "kind": link.kind.value,
    }


def _row_to_task(row: dict[str, Any]) -> Task:
    created_at = row["created_at"]
    resolved_at = row.get("resolved_at")
    return Task(
        project_key=str(row["project_key"]),
        task_id=str(row["task_id"]),
        kind=TaskKind(str(row["kind"])),
        type=str(row["type"]),
        title=str(row["title"]),
        body=str(row["body"]),
        priority=TaskPriority(str(row["priority"])),
        status=TaskStatus(str(row["status"])),
        origin=TaskOrigin(str(row["origin"])),
        source_story_id=(
            str(row["source_story_id"])
            if row.get("source_story_id") is not None
            else None
        ),
        execution_report_ref=(
            str(row["execution_report_ref"])
            if row.get("execution_report_ref") is not None
            else None
        ),
        created_at=(
            created_at
            if isinstance(created_at, datetime)
            else datetime.fromisoformat(str(created_at))
        ),
        resolved_at=(
            resolved_at
            if isinstance(resolved_at, datetime) or resolved_at is None
            else datetime.fromisoformat(str(resolved_at))
        ),
        resolved_by=(
            ResolvedBy(str(row["resolved_by"]))
            if row.get("resolved_by") is not None
            else None
        ),
    )


class StateBackendTaskRepository:
    """SQLite/Postgres-backed task-management repository."""

    def __init__(self, store_dir: Path | None = None) -> None:
        from pathlib import Path as _Path

        self._store_dir: Path = store_dir or _Path.cwd()

    def write_task(self, task: Task) -> None:
        """Persist a task row via the active state backend."""
        row = _task_to_row(task)
        if _is_postgres():
            self._pg_write_task(row)
            return
        self._sqlite_write_task(row)

    def get_task(self, project_key: str, task_id: str) -> Task | None:
        """Load one task by project-scoped identity."""
        if _is_postgres():
            return self._pg_get_task(project_key, task_id)
        return self._sqlite_get_task(project_key, task_id)

    def list_tasks(
        self,
        project_key: str,
        *,
        filter: TaskListFilter | None = None,  # noqa: A002
    ) -> list[Task]:
        """Load project-scoped tasks with optional filters."""
        if _is_postgres():
            return self._pg_list_tasks(project_key, task_filter=filter)
        return self._sqlite_list_tasks(project_key, task_filter=filter)

    def write_task_link(self, link: TaskLink) -> None:
        """Persist a task link via the active state backend."""
        row = _link_to_row(link)
        if _is_postgres():
            self._pg_write_task_link(row)
            return
        self._sqlite_write_task_link(row)

    def delete_task_link(self, link: TaskLink) -> bool:
        """Delete a task-link row and return whether a row was removed."""
        row = _link_to_row(link)
        if _is_postgres():
            return self._pg_delete_task_link(row)
        return self._sqlite_delete_task_link(row)

    def list_tasks_for_target(
        self,
        project_key: str,
        target_kind: TaskTargetKind,
        target_id: str,
    ) -> list[Task]:
        """Load tasks linked to a project-scoped target."""
        if _is_postgres():
            return self._pg_list_tasks_for_target(project_key, target_kind, target_id)
        return self._sqlite_list_tasks_for_target(project_key, target_kind, target_id)

    def story_target_exists(self, project_key: str, story_id: str) -> bool:
        """Return whether a canonical story row exists for the project."""
        if _is_postgres():
            return self._pg_story_target_exists(project_key, story_id)
        return self._sqlite_story_target_exists(project_key, story_id)

    def _sqlite_write_task(self, row: dict[str, object]) -> None:
        with _sqlite_connect_qa(self._store_dir) as conn:
            conn.execute(_SQLITE_UPSERT_TASK, row)

    def _pg_write_task(self, row: dict[str, object]) -> None:
        with _postgres_connect() as conn:
            conn.execute(_PG_UPSERT_TASK, row)

    def _sqlite_get_task(self, project_key: str, task_id: str) -> Task | None:
        with _sqlite_connect_qa(self._store_dir) as conn:
            row = conn.execute(
                "SELECT * FROM tm_tasks WHERE project_key = ? AND task_id = ?",
                (project_key, task_id),
            ).fetchone()
        return _row_to_task(dict(row)) if row is not None else None

    def _pg_get_task(self, project_key: str, task_id: str) -> Task | None:
        with _postgres_connect() as conn:
            row = conn.execute(
                "SELECT * FROM tm_tasks WHERE project_key = %s AND task_id = %s",
                (project_key, task_id),
            ).fetchone()
        return _row_to_task(dict(row)) if row is not None else None

    def _sqlite_list_tasks(
        self,
        project_key: str,
        *,
        task_filter: TaskListFilter | None,
    ) -> list[Task]:
        where, params = _build_task_where(project_key, task_filter, placeholder="?")
        with _sqlite_connect_qa(self._store_dir) as conn:
            rows = conn.execute(
                f"SELECT * FROM tm_tasks {where} ORDER BY created_at ASC, task_id ASC",
                tuple(params),
            ).fetchall()
        return [_row_to_task(dict(row)) for row in rows]

    def _pg_list_tasks(
        self,
        project_key: str,
        *,
        task_filter: TaskListFilter | None,
    ) -> list[Task]:
        where, params = _build_task_where(project_key, task_filter, placeholder="%s")
        with _postgres_connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM tm_tasks {where} ORDER BY created_at ASC, task_id ASC",
                tuple(params),
            ).fetchall()
        return [_row_to_task(dict(row)) for row in rows]

    def _sqlite_write_task_link(self, row: dict[str, object]) -> None:
        with _sqlite_connect_qa(self._store_dir) as conn:
            conn.execute(_SQLITE_INSERT_LINK, row)

    def _pg_write_task_link(self, row: dict[str, object]) -> None:
        with _postgres_connect() as conn:
            conn.execute(_PG_INSERT_LINK, row)

    def _sqlite_delete_task_link(self, row: dict[str, object]) -> bool:
        with _sqlite_connect_qa(self._store_dir) as conn:
            cursor = conn.execute(_SQLITE_DELETE_LINK, row)
            return int(cursor.rowcount) > 0

    def _pg_delete_task_link(self, row: dict[str, object]) -> bool:
        with _postgres_connect() as conn:
            cursor = conn.execute(_PG_DELETE_LINK, row)
            return int(cursor.rowcount) > 0

    def _sqlite_list_tasks_for_target(
        self,
        project_key: str,
        target_kind: TaskTargetKind,
        target_id: str,
    ) -> list[Task]:
        with _sqlite_connect_qa(self._store_dir) as conn:
            rows = conn.execute(
                _SQLITE_SELECT_TASKS_FOR_TARGET,
                (project_key, target_kind.value, target_id),
            ).fetchall()
        return [_row_to_task(dict(row)) for row in rows]

    def _pg_list_tasks_for_target(
        self,
        project_key: str,
        target_kind: TaskTargetKind,
        target_id: str,
    ) -> list[Task]:
        with _postgres_connect() as conn:
            rows = conn.execute(
                _PG_SELECT_TASKS_FOR_TARGET,
                (project_key, target_kind.value, target_id),
            ).fetchall()
        return [_row_to_task(dict(row)) for row in rows]

    def _sqlite_story_target_exists(self, project_key: str, story_id: str) -> bool:
        with _sqlite_connect_qa(self._store_dir) as conn:
            row = conn.execute(
                "SELECT 1 FROM stories WHERE project_key = ? AND story_display_id = ?",
                (project_key, story_id),
            ).fetchone()
        return row is not None

    def _pg_story_target_exists(self, project_key: str, story_id: str) -> bool:
        with _postgres_connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM stories WHERE project_key = %s AND story_display_id = %s",
                (project_key, story_id),
            ).fetchone()
        return row is not None


def _build_task_where(
    project_key: str,
    filter: TaskListFilter | None,  # noqa: A002
    *,
    placeholder: str,
) -> tuple[str, list[object]]:
    clauses = [f"project_key = {placeholder}"]
    params: list[object] = [project_key]
    if filter is not None:
        if filter.status is not None:
            clauses.append(f"status = {placeholder}")
            params.append(filter.status.value)
        if filter.type is not None:
            clauses.append(f"type = {placeholder}")
            params.append(filter.type)
        if filter.kind is not None:
            clauses.append(f"kind = {placeholder}")
            params.append(filter.kind.value)
        if filter.origin is not None:
            clauses.append(f"origin = {placeholder}")
            params.append(filter.origin.value)
    return f"WHERE {' AND '.join(clauses)}", params


_SQLITE_UPSERT_TASK = """
    INSERT INTO tm_tasks (
        project_key, task_id, kind, type, title, body, priority, status, origin,
        source_story_id, execution_report_ref, created_at, resolved_at, resolved_by
    ) VALUES (
        :project_key, :task_id, :kind, :type, :title, :body, :priority, :status,
        :origin, :source_story_id, :execution_report_ref, :created_at,
        :resolved_at, :resolved_by
    )
    ON CONFLICT(project_key, task_id) DO UPDATE SET
        kind = excluded.kind,
        type = excluded.type,
        title = excluded.title,
        body = excluded.body,
        priority = excluded.priority,
        status = excluded.status,
        origin = excluded.origin,
        source_story_id = excluded.source_story_id,
        execution_report_ref = excluded.execution_report_ref,
        created_at = excluded.created_at,
        resolved_at = excluded.resolved_at,
        resolved_by = excluded.resolved_by
"""

_PG_UPSERT_TASK = """
    INSERT INTO tm_tasks (
        project_key, task_id, kind, type, title, body, priority, status, origin,
        source_story_id, execution_report_ref, created_at, resolved_at, resolved_by
    ) VALUES (
        %(project_key)s, %(task_id)s, %(kind)s, %(type)s, %(title)s, %(body)s,
        %(priority)s, %(status)s, %(origin)s, %(source_story_id)s,
        %(execution_report_ref)s, %(created_at)s, %(resolved_at)s, %(resolved_by)s
    )
    ON CONFLICT(project_key, task_id) DO UPDATE SET
        kind = EXCLUDED.kind,
        type = EXCLUDED.type,
        title = EXCLUDED.title,
        body = EXCLUDED.body,
        priority = EXCLUDED.priority,
        status = EXCLUDED.status,
        origin = EXCLUDED.origin,
        source_story_id = EXCLUDED.source_story_id,
        execution_report_ref = EXCLUDED.execution_report_ref,
        created_at = EXCLUDED.created_at,
        resolved_at = EXCLUDED.resolved_at,
        resolved_by = EXCLUDED.resolved_by
"""

_SQLITE_INSERT_LINK = """
    INSERT INTO tm_task_links (
        project_key, task_id, target_kind, target_id, kind
    ) VALUES (
        :project_key, :task_id, :target_kind, :target_id, :kind
    )
    ON CONFLICT(project_key, task_id, target_kind, target_id, kind) DO NOTHING
"""

_PG_INSERT_LINK = """
    INSERT INTO tm_task_links (
        project_key, task_id, target_kind, target_id, kind
    ) VALUES (
        %(project_key)s, %(task_id)s, %(target_kind)s, %(target_id)s, %(kind)s
    )
    ON CONFLICT(project_key, task_id, target_kind, target_id, kind) DO NOTHING
"""

_SQLITE_DELETE_LINK = """
    DELETE FROM tm_task_links
    WHERE project_key = :project_key
      AND task_id = :task_id
      AND target_kind = :target_kind
      AND target_id = :target_id
      AND kind = :kind
"""

_PG_DELETE_LINK = """
    DELETE FROM tm_task_links
    WHERE project_key = %(project_key)s
      AND task_id = %(task_id)s
      AND target_kind = %(target_kind)s
      AND target_id = %(target_id)s
      AND kind = %(kind)s
"""

_SQLITE_SELECT_TASKS_FOR_TARGET = """
    SELECT t.*
    FROM tm_tasks t
    JOIN tm_task_links l
      ON l.project_key = t.project_key
     AND l.task_id = t.task_id
    WHERE l.project_key = ?
      AND l.target_kind = ?
      AND l.target_id = ?
    ORDER BY t.created_at ASC, t.task_id ASC
"""

_PG_SELECT_TASKS_FOR_TARGET = """
    SELECT t.*
    FROM tm_tasks t
    JOIN tm_task_links l
      ON l.project_key = t.project_key
     AND l.task_id = t.task_id
    WHERE l.project_key = %s
      AND l.target_kind = %s
      AND l.target_id = %s
    ORDER BY t.created_at ASC, t.task_id ASC
"""


__all__ = [
    "StateBackendTaskRepository",
    "TaskRepository",
]
