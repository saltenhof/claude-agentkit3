"""Transport-agnostic task-management service surface."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.task_management.errors import (
    InvalidTaskLinkTargetError,
    InvalidTaskTransitionError,
    TaskAlreadyExistsError,
    TaskLinkNotFoundError,
    TaskNotFoundError,
)
from agentkit.task_management.models import (
    ResolvedBy,
    Task,
    TaskLink,
    TaskListFilter,
    TaskStatus,
    TaskTargetKind,
)

if TYPE_CHECKING:
    from agentkit.telemetry.projection_accessor import ProjectionAccessor


class TaskManagement:
    """Transport-agnostic top surface for task state and links."""

    def __init__(self, accessor: ProjectionAccessor) -> None:
        self._accessor = accessor

    def create_task(self, task: Task) -> Task:
        """Create a task in the initial ``open`` state."""
        self._require_project_key(task.project_key)
        if task.status is not TaskStatus.OPEN or task.resolved_at is not None or task.resolved_by is not None:
            raise InvalidTaskTransitionError(task.task_id, task.status, "create_task")
        existing = self._accessor.get_task(task.project_key, task.task_id)
        if existing is not None:
            if existing == task:
                return existing
            raise TaskAlreadyExistsError(task.project_key, task.task_id)
        self._accessor.record_task(task)
        return task

    def link_task(self, link: TaskLink) -> TaskLink:
        """Create a task link without changing the source task status."""
        self._require_project_key(link.project_key)
        self._require_task(link.project_key, link.task_id)
        self._validate_target(link)
        self._accessor.record_task_link(link)
        return link

    def unlink_task(self, link: TaskLink) -> None:
        """Remove an existing task link without changing the source task status."""
        self._require_project_key(link.project_key)
        self._require_task(link.project_key, link.task_id)
        if not self._accessor.delete_task_link(link):
            raise TaskLinkNotFoundError(
                link.project_key,
                link.task_id,
                link.target_kind,
                link.target_id,
                link.kind,
            )

    def resolve_task(
        self,
        project_key: str,
        task_id: str,
        resolved_by: ResolvedBy,
        *,
        resolved_at: datetime | None = None,
    ) -> Task:
        """Transition an open task to ``done``."""
        task = self._require_task(project_key, task_id)
        return self._close_task(
            task,
            command="resolve_task",
            status=TaskStatus.DONE,
            resolved_by=resolved_by,
            resolved_at=resolved_at,
        )

    def dismiss_task(
        self,
        project_key: str,
        task_id: str,
        resolved_by: ResolvedBy,
        *,
        resolved_at: datetime | None = None,
    ) -> Task:
        """Transition an open task to ``dismissed``."""
        task = self._require_task(project_key, task_id)
        return self._close_task(
            task,
            command="dismiss_task",
            status=TaskStatus.DISMISSED,
            resolved_by=resolved_by,
            resolved_at=resolved_at,
        )

    def get_task(self, project_key: str, task_id: str) -> Task:
        """Return one task from the explicit project partition."""
        return self._require_task(project_key, task_id)

    def list_tasks(
        self,
        project_key: str,
        filter: TaskListFilter | None = None,  # noqa: A002
    ) -> list[Task]:
        """List tasks from one project partition, optionally filtered."""
        self._require_project_key(project_key)
        return self._accessor.list_tasks(project_key, filter=filter)

    def list_tasks_for_target(
        self,
        project_key: str,
        target_kind: TaskTargetKind,
        target_id: str,
    ) -> list[Task]:
        """List tasks linked to one target within the explicit project partition."""
        self._require_project_key(project_key)
        target = TaskTargetKind(target_kind)
        if not target_id:
            raise ValueError("target_id is required")
        return self._accessor.list_tasks_for_target(project_key, target, target_id)

    def list_task_links(self, project_key: str) -> list[TaskLink]:
        """List every outgoing task link of one project partition (AG3-105/AC4).

        Returns all ``TaskLink`` edges in the project so a list view can bucket
        them by ``task_id`` and render each task's own (outgoing) links from
        backend truth in a single read. This complements the reverse read
        ``list_tasks_for_target`` (tasks linking TO a target). The data is
        already modeled (``TaskLink``); this read merely exposes it (FK-77
        §77.7, AG3-105/AC11). It mirrors no status — the link edge is a pure
        reference (FK-77 §77.3).
        """
        self._require_project_key(project_key)
        return self._accessor.list_task_links(project_key)

    def _close_task(
        self,
        task: Task,
        *,
        command: str,
        status: TaskStatus,
        resolved_by: ResolvedBy,
        resolved_at: datetime | None,
    ) -> Task:
        if task.status is not TaskStatus.OPEN:
            raise InvalidTaskTransitionError(task.task_id, task.status, command)
        closed_at = self._normalize_resolution_time(resolved_at)
        closed = task.model_copy(
            update={
                "status": status,
                "resolved_by": resolved_by,
                "resolved_at": closed_at,
            },
        )
        self._accessor.record_task(closed)
        return closed

    def _validate_target(self, link: TaskLink) -> None:
        if link.target_kind is TaskTargetKind.TASK:
            target = self._accessor.get_task(link.project_key, link.target_id)
            if target is None:
                raise InvalidTaskLinkTargetError(
                    link.project_key,
                    link.target_kind,
                    link.target_id,
                )
            return
        if not self._accessor.story_target_exists(link.project_key, link.target_id):
            raise InvalidTaskLinkTargetError(
                link.project_key,
                link.target_kind,
                link.target_id,
            )

    def _require_task(self, project_key: str, task_id: str) -> Task:
        self._require_project_key(project_key)
        if not task_id:
            raise ValueError("task_id is required")
        task = self._accessor.get_task(project_key, task_id)
        if task is None:
            raise TaskNotFoundError(project_key, task_id)
        return task

    @staticmethod
    def _require_project_key(project_key: str) -> None:
        if not project_key:
            raise ValueError("project_key is required")

    @staticmethod
    def _normalize_resolution_time(value: datetime | None) -> datetime:
        resolved_at = value or datetime.now(UTC)
        if resolved_at.tzinfo is None or resolved_at.utcoffset() is None:
            raise ValueError("resolved_at must be a timezone-aware UTC instant")
        return resolved_at.astimezone(UTC)
