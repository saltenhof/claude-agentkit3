"""Task-management HTTP routes (AG3-105 / FK-77 §77.7).

Mounts under ``/v1/projects/{project_key}/tasks``.

Endpoints:
  GET  /v1/projects/{key}/tasks                              -- list tasks
  GET  /v1/projects/{key}/task-links                         -- list all task links (AG3-105)
  GET  /v1/projects/{key}/tasks/for-target/{kind}/{id}       -- tasks for target
  GET  /v1/projects/{key}/tasks/{task_id}                    -- get task
  POST /v1/projects/{key}/tasks                              -- create task
  POST /v1/projects/{key}/tasks/{task_id}/resolve            -- resolve task
  POST /v1/projects/{key}/tasks/{task_id}/dismiss            -- dismiss task
  POST /v1/projects/{key}/tasks/{task_id}/links              -- link task
  POST /v1/projects/{key}/tasks/{task_id}/links/delete       -- unlink task

Fail-closed:
  - When ``task_management`` is None: all endpoints return 503 ``task_management_unavailable``.
  - Unexpected programming/infrastructure errors return 500 ``internal_error`` (NOT 503).
  - 503 is reserved for genuine service-unavailability (None service, ConfigError-style setup).

server-side task_id allocation:
  POST /tasks does NOT accept a client-supplied ``task_id``. The adapter allocates
  the canonical ``TM-YYYY-NNNN`` id server-side by inspecting the existing tasks for
  the project: sequence = max existing TM-{year}-{N} suffix for that year + 1.
  On the rare ``TaskAlreadyExistsError`` (race/collision) the adapter retries once.
  This keeps the allocation logic thin and co-located with the HTTP adapter, without
  modifying the BC service (which is stable and not in scope for this change).

Link targets: only ``task`` and ``story`` are valid target_kind values.
Requests with any other value are rejected with 422 (Pydantic validation).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError

from agentkit.control_plane.models import (
    BcRouteResponse,
    bc_error_response,
    bc_json_response,
    bc_unavailable_response,
)
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
    TaskKind,
    TaskLink,
    TaskListFilter,
    TaskOrigin,
    TaskPriority,
    TaskRelationKind,
    TaskStatus,
    TaskTargetKind,
)

if TYPE_CHECKING:
    from agentkit.task_management.service import TaskManagement

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Route patterns
# ---------------------------------------------------------------------------

_TASKS_COLLECTION = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/tasks/?$"
)
_TASKS_FOR_TARGET = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/tasks/for-target"
    r"/(?P<target_kind>[^/]+)/(?P<target_id>[^/]+)/?$"
)
# AG3-105/AC4: project-wide link read. Lives at /task-links (NOT under /tasks/)
# so it can never be shadowed by the /tasks/{task_id} detail route.
_TASK_LINKS_LIST = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/task-links/?$"
)
_TASK_DETAIL = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/tasks/(?P<task_id>[^/]+)/?$"
)
_TASK_RESOLVE = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/tasks/(?P<task_id>[^/]+)/resolve/?$"
)
_TASK_DISMISS = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/tasks/(?P<task_id>[^/]+)/dismiss/?$"
)
_TASK_LINKS = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/tasks/(?P<task_id>[^/]+)/links/?$"
)
_TASK_LINKS_DELETE = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/tasks/(?P<task_id>[^/]+)/links/delete/?$"
)

# Pattern to extract year + sequence suffix from a canonical task_id.
_TASK_ID_RE = re.compile(r"^TM-(\d{4})-(\d+)$")

# ---------------------------------------------------------------------------
# Internal request models (Pydantic, fail-closed validation)
# ---------------------------------------------------------------------------


class _CreateTaskRequest(BaseModel):
    """Wire body for POST /tasks (create task).

    task_id is NOT accepted from the client — allocated server-side (finding 9).
    The adapter derives the id as TM-{year}-{padded_seq} using the current year and
    the next available sequence for that year.
    """

    model_config = ConfigDict(extra="forbid")

    kind: TaskKind
    type: str
    title: str
    body: str
    priority: TaskPriority
    origin: TaskOrigin
    source_story_id: str | None = None


class _ResolveRequest(BaseModel):
    """Wire body for POST /tasks/{id}/resolve and /dismiss."""

    model_config = ConfigDict(extra="forbid")

    resolved_by: ResolvedBy


class _LinkRequest(BaseModel):
    """Wire body for POST /tasks/{id}/links and /links/delete.

    target_kind is restricted to TaskTargetKind (task|story only).
    Any other value is rejected at validation time with ValidationError -> 422.
    """

    model_config = ConfigDict(extra="forbid")

    target_kind: TaskTargetKind
    target_id: str
    kind: TaskRelationKind


# ---------------------------------------------------------------------------
# Server-side task_id allocation (finding 9)
# ---------------------------------------------------------------------------


def _allocate_task_id(project_key: str, service: TaskManagement) -> str:
    """Allocate the next canonical TM-YYYY-NNNN task_id for a project.

    Algorithm:
      1. List all existing tasks for the project.
      2. Find the maximum existing sequence number for tasks created in the current
         calendar year (by parsing the TM-{year}-{seq} pattern).
      3. Return TM-{year}-{max_seq+1}, zero-padded to at least 4 digits.

    Caller must retry on TaskAlreadyExistsError (rare race condition).
    """
    year = datetime.now(UTC).year
    year_str = str(year)
    existing = service.list_tasks(project_key, TaskListFilter())
    max_seq = 0
    for task in existing:
        m = _TASK_ID_RE.match(task.task_id)
        if m and m.group(1) == year_str:
            seq = int(m.group(2))
            if seq > max_seq:
                max_seq = seq
    next_seq = max_seq + 1
    return f"TM-{year}-{next_seq:04d}"


# ---------------------------------------------------------------------------
# Internal helpers — 500 vs 503 distinction
# ---------------------------------------------------------------------------


def _internal_error(message: str, correlation_id: str, exc: Exception) -> BcRouteResponse:
    """Return 500 internal_error for unexpected (programming/runtime) exceptions.

    This is intentionally loud: unexpected exceptions should NOT be masked as
    service-unavailability (503). Callers log at ERROR level.
    """
    logger.error("Unexpected internal error: %s — %s", message, exc, exc_info=True)
    return bc_error_response(
        HTTPStatus.INTERNAL_SERVER_ERROR,
        error_code="internal_error",
        message=f"{message}: {exc}",
        correlation_id=correlation_id,
    )


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskManagementRoutes:
    """Route handler for the task-management BC HTTP surface (AG3-105 / FK-77 §77.7).

    Fail-closed rules:
      - ``task_management is None``: 503 ``task_management_unavailable`` for every route.
      - Known domain exceptions (TaskNotFoundError, InvalidTaskTransitionError, etc.):
        explicit 4xx per the contract.
      - Truly unexpected exceptions (programming bugs, unexpected DB errors): 500
        ``internal_error`` — loud failure, NOT masked as 503.

    Args:
        task_management: Optional ``TaskManagement`` service. When ``None`` all
            routes return ``503 task_management_unavailable`` (fail-closed).
    """

    task_management: TaskManagement | None = None

    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> BcRouteResponse | None:
        """Handle task-management GET routes or return None.

        Args:
            route_path: Resolved URL path.
            query: Parsed query-string parameters.
            correlation_id: Request correlation ID.

        Returns:
            ``BcRouteResponse`` when the route is claimed, ``None`` otherwise.
        """
        # task-links (project-wide link read, AG3-105/AC4) — own path segment.
        links_list_match = _TASK_LINKS_LIST.match(route_path)
        if links_list_match is not None:
            return self._handle_list_task_links(
                links_list_match.group("project_key"),
                correlation_id,
            )

        # for-target before collection (more specific path first)
        target_match = _TASKS_FOR_TARGET.match(route_path)
        if target_match is not None:
            return self._handle_list_for_target(
                target_match.group("project_key"),
                target_match.group("target_kind"),
                target_match.group("target_id"),
                correlation_id,
            )

        collection_match = _TASKS_COLLECTION.match(route_path)
        if collection_match is not None:
            return self._handle_list_tasks(
                collection_match.group("project_key"),
                query,
                correlation_id,
            )

        detail_match = _TASK_DETAIL.match(route_path)
        if detail_match is not None:
            return self._handle_get_task(
                detail_match.group("project_key"),
                detail_match.group("task_id"),
                correlation_id,
            )

        return None

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> BcRouteResponse | None:
        """Handle task-management POST routes or return None.

        Args:
            route_path: Resolved URL path.
            payload: Decoded JSON body (dict or None).
            correlation_id: Request correlation ID.

        Returns:
            ``BcRouteResponse`` when the route is claimed, ``None`` otherwise.
        """
        # links/delete before links (more specific path first)
        links_delete_match = _TASK_LINKS_DELETE.match(route_path)
        if links_delete_match is not None:
            return self._handle_unlink_task(
                links_delete_match.group("project_key"),
                links_delete_match.group("task_id"),
                payload,
                correlation_id,
            )

        links_match = _TASK_LINKS.match(route_path)
        if links_match is not None:
            return self._handle_link_task(
                links_match.group("project_key"),
                links_match.group("task_id"),
                payload,
                correlation_id,
            )

        resolve_match = _TASK_RESOLVE.match(route_path)
        if resolve_match is not None:
            return self._handle_resolve_task(
                resolve_match.group("project_key"),
                resolve_match.group("task_id"),
                payload,
                correlation_id,
            )

        dismiss_match = _TASK_DISMISS.match(route_path)
        if dismiss_match is not None:
            return self._handle_dismiss_task(
                dismiss_match.group("project_key"),
                dismiss_match.group("task_id"),
                payload,
                correlation_id,
            )

        collection_match = _TASKS_COLLECTION.match(route_path)
        if collection_match is not None:
            return self._handle_create_task(
                collection_match.group("project_key"),
                payload,
                correlation_id,
            )

        return None

    def handle_delete(
        self,
        _route_path: str,
        _correlation_id: str,
    ) -> BcRouteResponse | None:
        """Handle task-management DELETE routes (none — returns None always).

        Task deletions use POST .../links/delete pattern, not HTTP DELETE.
        """
        return None

    # ------------------------------------------------------------------
    # Private helpers — availability guard
    # ------------------------------------------------------------------

    def _unavailable(self, correlation_id: str) -> BcRouteResponse:
        """503 for genuine service unavailability (service is None / unconfigured)."""
        return bc_unavailable_response(
            "task_management_unavailable",
            message="Task-management service is not available (AG3-105 / FK-77 §77.7)",
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Private helpers — GET handlers
    # ------------------------------------------------------------------

    def _handle_list_tasks(
        self,
        project_key: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> BcRouteResponse:
        if self.task_management is None:
            return self._unavailable(correlation_id)
        try:
            status_raw = query.get("status", [None])[0] or None
            type_raw = query.get("type", [None])[0] or None
            kind_raw = query.get("kind", [None])[0] or None
            origin_raw = query.get("origin", [None])[0] or None
            task_filter = TaskListFilter(
                status=TaskStatus(status_raw) if status_raw else None,
                type=type_raw,
                kind=TaskKind(kind_raw) if kind_raw else None,
                origin=TaskOrigin(origin_raw) if origin_raw else None,
            )
            tasks = self.task_management.list_tasks(project_key, task_filter)
        except ValueError as exc:
            return bc_error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_task_filter",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            # Unexpected error — 500 (not 503, not masked as unavailable)
            return _internal_error("list_tasks failed unexpectedly", correlation_id, exc)
        return bc_json_response(
            HTTPStatus.OK,
            {
                "tasks": [t.model_dump(mode="json") for t in tasks],
                "project_key": project_key,
            },
            correlation_id=correlation_id,
        )

    def _handle_list_for_target(
        self,
        project_key: str,
        target_kind: str,
        target_id: str,
        correlation_id: str,
    ) -> BcRouteResponse:
        if self.task_management is None:
            return self._unavailable(correlation_id)
        try:
            tasks = self.task_management.list_tasks_for_target(
                project_key, TaskTargetKind(target_kind), target_id
            )
        except ValueError as exc:
            return bc_error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_target_kind",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            return _internal_error("list_tasks_for_target failed unexpectedly", correlation_id, exc)
        return bc_json_response(
            HTTPStatus.OK,
            {
                "tasks": [t.model_dump(mode="json") for t in tasks],
                "project_key": project_key,
            },
            correlation_id=correlation_id,
        )

    def _handle_list_task_links(
        self,
        project_key: str,
        correlation_id: str,
    ) -> BcRouteResponse:
        """List all task links for one project (AG3-105/AC4 backend hydration)."""
        if self.task_management is None:
            return self._unavailable(correlation_id)
        try:
            links = self.task_management.list_task_links(project_key)
        except ValueError as exc:
            return bc_error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_task_links_query",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            return _internal_error("list_task_links failed unexpectedly", correlation_id, exc)
        return bc_json_response(
            HTTPStatus.OK,
            {
                "links": [link.model_dump(mode="json") for link in links],
                "project_key": project_key,
            },
            correlation_id=correlation_id,
        )

    def _handle_get_task(
        self,
        project_key: str,
        task_id: str,
        correlation_id: str,
    ) -> BcRouteResponse:
        if self.task_management is None:
            return self._unavailable(correlation_id)
        try:
            task = self.task_management.get_task(project_key, task_id)
        except TaskNotFoundError as exc:
            return bc_error_response(
                HTTPStatus.NOT_FOUND,
                error_code="task_not_found",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            return _internal_error("get_task failed unexpectedly", correlation_id, exc)
        return bc_json_response(
            HTTPStatus.OK,
            {"task": task.model_dump(mode="json"), "project_key": project_key},
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Private helpers — POST handlers
    # ------------------------------------------------------------------

    def _handle_create_task(
        self,
        project_key: str,
        payload: object,
        correlation_id: str,
    ) -> BcRouteResponse:
        """Create a task with server-side task_id allocation (finding 9).

        Does NOT accept task_id from the client. Allocates TM-{year}-{seq} using the
        existing task count for this year. Retries once on TaskAlreadyExistsError
        (rare allocation collision — e.g. concurrent requests).
        """
        if self.task_management is None:
            return self._unavailable(correlation_id)
        try:
            body = _CreateTaskRequest.model_validate(payload or {})
        except ValidationError as exc:
            return bc_error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code="invalid_task_payload",
                message=str(exc),
                correlation_id=correlation_id,
            )

        # Allocate task_id server-side with a single retry on collision.
        max_attempts = 2
        for attempt in range(max_attempts):
            response = self._attempt_create_task(
                project_key,
                body,
                correlation_id,
                is_last_attempt=attempt == max_attempts - 1,
            )
            if response is not None:
                return response
            # None == allocation collision and retries remain.
            logger.warning("task_id collision for project %s, retrying", project_key)

        # Should never be reached — the loop always returns on the last attempt.
        return _internal_error(  # pragma: no cover
            "create_task allocation loop exhausted", correlation_id, RuntimeError("unreachable")
        )

    def _attempt_create_task(
        self,
        project_key: str,
        body: _CreateTaskRequest,
        correlation_id: str,
        *,
        is_last_attempt: bool,
    ) -> BcRouteResponse | None:
        """Run one create attempt; return ``None`` on a retryable id collision.

        A ``None`` result means the allocated id collided and the caller still has
        retries left. Every other outcome (success or terminal error) returns a
        concrete ``BcRouteResponse``.
        """
        assert self.task_management is not None  # noqa: S101 — guarded by caller
        try:
            task_id = _allocate_task_id(project_key, self.task_management)
        except Exception as exc:  # noqa: BLE001
            return _internal_error("task_id allocation failed", correlation_id, exc)
        try:
            task = Task(
                task_id=task_id,
                project_key=project_key,
                kind=body.kind,
                type=body.type,
                title=body.title,
                body=body.body,
                priority=body.priority,
                status=TaskStatus.OPEN,
                origin=body.origin,
                source_story_id=body.source_story_id,
                execution_report_ref=None,
                created_at=datetime.now(UTC),
                resolved_at=None,
                resolved_by=None,
            )
            created = self.task_management.create_task(task)
        except TaskAlreadyExistsError:
            if not is_last_attempt:
                return None
            return bc_error_response(
                HTTPStatus.CONFLICT,
                error_code="task_already_exists",
                message=f"Task {task_id} already exists after allocation retries",
                correlation_id=correlation_id,
            )
        except InvalidTaskTransitionError as exc:
            return bc_error_response(
                HTTPStatus.CONFLICT,
                error_code="invalid_task_transition",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except ValueError as exc:
            return bc_error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_task",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            return _internal_error("create_task failed unexpectedly", correlation_id, exc)
        return bc_json_response(
            HTTPStatus.CREATED,
            {"task": created.model_dump(mode="json"), "project_key": project_key},
            correlation_id=correlation_id,
        )

    def _handle_resolve_task(
        self,
        project_key: str,
        task_id: str,
        payload: object,
        correlation_id: str,
    ) -> BcRouteResponse:
        if self.task_management is None:
            return self._unavailable(correlation_id)
        try:
            body = _ResolveRequest.model_validate(payload or {})
        except ValidationError as exc:
            return bc_error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code="invalid_resolve_payload",
                message=str(exc),
                correlation_id=correlation_id,
            )
        try:
            task = self.task_management.resolve_task(
                project_key, task_id, body.resolved_by
            )
        except TaskNotFoundError as exc:
            return bc_error_response(
                HTTPStatus.NOT_FOUND,
                error_code="task_not_found",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except InvalidTaskTransitionError as exc:
            return bc_error_response(
                HTTPStatus.CONFLICT,
                error_code="invalid_task_transition",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            return _internal_error("resolve_task failed unexpectedly", correlation_id, exc)
        return bc_json_response(
            HTTPStatus.OK,
            {"task": task.model_dump(mode="json"), "project_key": project_key},
            correlation_id=correlation_id,
        )

    def _handle_dismiss_task(
        self,
        project_key: str,
        task_id: str,
        payload: object,
        correlation_id: str,
    ) -> BcRouteResponse:
        if self.task_management is None:
            return self._unavailable(correlation_id)
        try:
            body = _ResolveRequest.model_validate(payload or {})
        except ValidationError as exc:
            return bc_error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code="invalid_dismiss_payload",
                message=str(exc),
                correlation_id=correlation_id,
            )
        try:
            task = self.task_management.dismiss_task(
                project_key, task_id, body.resolved_by
            )
        except TaskNotFoundError as exc:
            return bc_error_response(
                HTTPStatus.NOT_FOUND,
                error_code="task_not_found",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except InvalidTaskTransitionError as exc:
            return bc_error_response(
                HTTPStatus.CONFLICT,
                error_code="invalid_task_transition",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            return _internal_error("dismiss_task failed unexpectedly", correlation_id, exc)
        return bc_json_response(
            HTTPStatus.OK,
            {"task": task.model_dump(mode="json"), "project_key": project_key},
            correlation_id=correlation_id,
        )

    def _handle_link_task(
        self,
        project_key: str,
        task_id: str,
        payload: object,
        correlation_id: str,
    ) -> BcRouteResponse:
        if self.task_management is None:
            return self._unavailable(correlation_id)
        try:
            body = _LinkRequest.model_validate(payload or {})
        except ValidationError as exc:
            return bc_error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code="invalid_link_payload",
                message=str(exc),
                correlation_id=correlation_id,
            )
        try:
            link = self.task_management.link_task(
                TaskLink(
                    project_key=project_key,
                    task_id=task_id,
                    target_kind=body.target_kind,
                    target_id=body.target_id,
                    kind=body.kind,
                )
            )
        except TaskNotFoundError as exc:
            return bc_error_response(
                HTTPStatus.NOT_FOUND,
                error_code="task_not_found",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except InvalidTaskLinkTargetError as exc:
            return bc_error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code="invalid_task_link_target",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            return _internal_error("link_task failed unexpectedly", correlation_id, exc)
        return bc_json_response(
            HTTPStatus.CREATED,
            {"link": link.model_dump(mode="json")},
            correlation_id=correlation_id,
        )

    def _handle_unlink_task(
        self,
        project_key: str,
        task_id: str,
        payload: object,
        correlation_id: str,
    ) -> BcRouteResponse:
        if self.task_management is None:
            return self._unavailable(correlation_id)
        try:
            body = _LinkRequest.model_validate(payload or {})
        except ValidationError as exc:
            return bc_error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code="invalid_link_payload",
                message=str(exc),
                correlation_id=correlation_id,
            )
        try:
            self.task_management.unlink_task(
                TaskLink(
                    project_key=project_key,
                    task_id=task_id,
                    target_kind=body.target_kind,
                    target_id=body.target_id,
                    kind=body.kind,
                )
            )
        except TaskNotFoundError as exc:
            return bc_error_response(
                HTTPStatus.NOT_FOUND,
                error_code="task_not_found",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except TaskLinkNotFoundError as exc:
            return bc_error_response(
                HTTPStatus.NOT_FOUND,
                error_code="task_link_not_found",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            return _internal_error("unlink_task failed unexpectedly", correlation_id, exc)
        return bc_json_response(
            HTTPStatus.OK,
            {},
            correlation_id=correlation_id,
        )
