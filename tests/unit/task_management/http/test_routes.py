"""Unit tests for TaskManagementRoutes (AG3-105 / FK-77 §77.7).

Tests use real TaskManagement + real ProjectionAccessor + real StateBackendTaskRepository
via tmp_path (SQLite). No mocks — fail-closed principle.

Finding 9 (server-side task_id): POST /tasks does NOT accept task_id from the client.
  - _CreateTaskRequest does not have a task_id field.
  - The adapter allocates TM-{year}-{seq} server-side.

Finding 8 (500 vs 503):
  - 503 = service is None (genuine unavailability).
  - 500 = unexpected programming/runtime error (NOT masked as 503).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.backend.task_management.http.routes import TaskManagementRoutes
from agentkit.backend.task_management.service import TaskManagement
from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_NOW = datetime(2026, 6, 16, 10, 0, tzinfo=UTC)


@pytest.fixture()
def routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TaskManagementRoutes]:
    """Real TaskManagementRoutes backed by SQLite in tmp_path."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
    service = TaskManagement(accessor)
    yield TaskManagementRoutes(task_management=service)
    reset_backend_cache_for_tests()


_CORR = "test-corr-001"
_PROJ = "PROJ"


def _body(data: dict) -> object:
    return data


def _task_payload(
    *,
    kind: str = "actionable",
    task_type: str = "concept_update",
    title: str = "Test Task",
    body: str = "Body text",
    priority: str = "normal",
    origin: str = "human",
    source_story_id: str | None = None,
) -> dict:
    """Create a task wire payload WITHOUT task_id (server-side allocation, finding 9)."""
    payload: dict = {
        "kind": kind,
        "type": task_type,
        "title": title,
        "body": body,
        "priority": priority,
        "origin": origin,
    }
    if source_story_id is not None:
        payload["source_story_id"] = source_story_id
    return payload


class TestHandleGetListTasksEmpty:
    def test_list_tasks_empty(self, routes: TaskManagementRoutes) -> None:
        resp = routes.handle_get(f"/v1/projects/{_PROJ}/tasks", {}, _CORR)
        assert resp is not None
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["tasks"] == []
        assert body["project_key"] == _PROJ

    def test_non_matching_path_returns_none(self, routes: TaskManagementRoutes) -> None:
        resp = routes.handle_get("/v1/projects/PROJ/kpi/stories", {}, _CORR)
        assert resp is None

    def test_for_target_path_not_captured_by_collection(
        self, routes: TaskManagementRoutes
    ) -> None:
        # for-target path must not be captured by _TASKS_COLLECTION
        resp = routes.handle_get(
            "/v1/projects/PROJ/tasks/for-target/story/AG3-001", {}, _CORR
        )
        assert resp is not None
        # Should return tasks (empty list, no error)
        body = json.loads(resp.body)
        assert "tasks" in body


class TestHandleGetSingleTask:
    def test_get_task_after_create(self, routes: TaskManagementRoutes) -> None:
        create_resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks",
            _task_payload(title="Get After Create"),
            _CORR,
        )
        assert create_resp is not None
        assert create_resp.status_code == 201
        created_body = json.loads(create_resp.body)
        task_id = created_body["task"]["task_id"]
        # task_id is allocated server-side — must match TM-YYYY-NNNN pattern
        assert task_id.startswith("TM-")

        get_resp = routes.handle_get(
            f"/v1/projects/{_PROJ}/tasks/{task_id}", {}, _CORR
        )
        assert get_resp is not None
        assert get_resp.status_code == 200
        body = json.loads(get_resp.body)
        assert body["task"]["task_id"] == task_id
        assert body["task"]["status"] == "open"

    def test_get_missing_task_returns_404(self, routes: TaskManagementRoutes) -> None:
        resp = routes.handle_get(
            f"/v1/projects/{_PROJ}/tasks/TM-9999-9999", {}, _CORR
        )
        assert resp is not None
        assert resp.status_code == 404
        body = json.loads(resp.body)
        assert body["error_code"] == "task_not_found"


class TestHandlePostCreateTask:
    def test_create_task_returns_201_with_server_allocated_id(
        self, routes: TaskManagementRoutes
    ) -> None:
        """POST /tasks returns 201; task_id is allocated server-side (finding 9)."""
        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks",
            _task_payload(title="Server-Allocated Task"),
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 201
        body = json.loads(resp.body)
        # task_id is server-allocated — must start with TM-
        assert body["task"]["task_id"].startswith("TM-")
        assert body["task"]["status"] == "open"
        assert body["project_key"] == _PROJ

    def test_create_task_rejected_with_task_id_in_payload(
        self, routes: TaskManagementRoutes
    ) -> None:
        """task_id in the request body is rejected (extra='forbid', finding 9)."""
        payload_with_id = {**_task_payload(), "task_id": "TM-2026-0001"}
        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks",
            payload_with_id,
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 422
        body = json.loads(resp.body)
        assert body["error_code"] == "invalid_task_payload"

    def test_create_sequential_ids(self, routes: TaskManagementRoutes) -> None:
        """Two sequential creates for the same project produce ascending TM-{year}-NNNN ids."""
        resp1 = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks",
            _task_payload(title="First"),
            _CORR,
        )
        resp2 = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks",
            _task_payload(title="Second"),
            _CORR,
        )
        assert resp1 is not None and resp2 is not None
        id1 = json.loads(resp1.body)["task"]["task_id"]
        id2 = json.loads(resp2.body)["task"]["task_id"]
        assert id1 != id2
        # Both are canonical TM-YYYY-NNNN
        assert id1.startswith("TM-")
        assert id2.startswith("TM-")
        # Sequence of second is greater than first
        seq1 = int(id1.split("-")[2])
        seq2 = int(id2.split("-")[2])
        assert seq2 > seq1


class TestHandlePostResolveAndDismiss:
    def test_resolve_task_returns_done(self, routes: TaskManagementRoutes) -> None:
        create = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks",
            _task_payload(title="Resolve Test"),
            _CORR,
        )
        assert create is not None
        task_id = json.loads(create.body)["task"]["task_id"]

        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/resolve",
            {"resolved_by": "human"},
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["task"]["status"] == "done"

    def test_dismiss_task_returns_dismissed(self, routes: TaskManagementRoutes) -> None:
        create = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks",
            _task_payload(title="Dismiss Test"),
            _CORR,
        )
        assert create is not None
        task_id = json.loads(create.body)["task"]["task_id"]

        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/dismiss",
            {"resolved_by": "agent"},
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["task"]["status"] == "dismissed"

    def test_resolve_and_dismiss_are_separate(
        self, routes: TaskManagementRoutes
    ) -> None:
        """resolve calls resolve_task (done), dismiss calls dismiss_task (dismissed)."""
        c1 = routes.handle_post(f"/v1/projects/{_PROJ}/tasks", _task_payload(title="T1"), _CORR)
        c2 = routes.handle_post(f"/v1/projects/{_PROJ}/tasks", _task_payload(title="T2"), _CORR)
        assert c1 is not None and c2 is not None
        id1 = json.loads(c1.body)["task"]["task_id"]
        id2 = json.loads(c2.body)["task"]["task_id"]

        r1 = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{id1}/resolve",
            {"resolved_by": "human"},
            _CORR,
        )
        assert r1 is not None
        assert json.loads(r1.body)["task"]["status"] == "done"

        r2 = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{id2}/dismiss",
            {"resolved_by": "human"},
            _CORR,
        )
        assert r2 is not None
        assert json.loads(r2.body)["task"]["status"] == "dismissed"

        # First is still done (not dismissed)
        get1 = routes.handle_get(f"/v1/projects/{_PROJ}/tasks/{id1}", {}, _CORR)
        assert get1 is not None
        assert json.loads(get1.body)["task"]["status"] == "done"


class TestTenantScope:
    def test_tenant_scope(self, routes: TaskManagementRoutes) -> None:
        """Create same logical task in PROJ-A and PROJ-B — each only sees its own."""
        routes.handle_post("/v1/projects/PROJ-A/tasks", _task_payload(title="Task A"), _CORR)
        routes.handle_post("/v1/projects/PROJ-B/tasks", _task_payload(title="Task B"), _CORR)

        list_a = routes.handle_get("/v1/projects/PROJ-A/tasks", {}, _CORR)
        assert list_a is not None
        body_a = json.loads(list_a.body)
        assert len(body_a["tasks"]) == 1
        assert body_a["tasks"][0]["project_key"] == "PROJ-A"

        list_b = routes.handle_get("/v1/projects/PROJ-B/tasks", {}, _CORR)
        assert list_b is not None
        body_b = json.loads(list_b.body)
        assert len(body_b["tasks"]) == 1
        assert body_b["tasks"][0]["project_key"] == "PROJ-B"


class TestLinkEndpoints:
    def test_link_target_task_ok(self, routes: TaskManagementRoutes) -> None:
        """Linking to another task returns 201."""
        c1 = routes.handle_post(f"/v1/projects/{_PROJ}/tasks", _task_payload(title="Source"), _CORR)
        c2 = routes.handle_post(f"/v1/projects/{_PROJ}/tasks", _task_payload(title="Target"), _CORR)
        assert c1 is not None and c2 is not None
        id1 = json.loads(c1.body)["task"]["task_id"]
        id2 = json.loads(c2.body)["task"]["task_id"]

        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{id1}/links",
            {"target_kind": "task", "target_id": id2, "kind": "relates_to"},
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 201
        body = json.loads(resp.body)
        assert body["link"]["target_kind"] == "task"

    def test_link_target_story_invalid_returns_422(self, routes: TaskManagementRoutes) -> None:
        """Linking to a non-existent story returns 422 (InvalidTaskLinkTargetError)."""
        create = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks",
            _task_payload(title="Link Story Test"),
            _CORR,
        )
        assert create is not None
        task_id = json.loads(create.body)["task"]["task_id"]

        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/links",
            {"target_kind": "story", "target_id": "AG3-001", "kind": "relates_to"},
            _CORR,
        )
        assert resp is not None
        # Story doesn't exist in test DB -> 422
        assert resp.status_code == 422
        body = json.loads(resp.body)
        assert body["error_code"] == "invalid_task_link_target"

    def test_link_target_invalid_kind_rejected(
        self, routes: TaskManagementRoutes
    ) -> None:
        """target_kind='artifact' is rejected with 422 (Pydantic validation)."""
        create = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks",
            _task_payload(title="Artifact Reject Test"),
            _CORR,
        )
        assert create is not None
        task_id = json.loads(create.body)["task"]["task_id"]

        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/links",
            {"target_kind": "artifact", "target_id": "some-artifact", "kind": "relates_to"},
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 422
        body = json.loads(resp.body)
        assert body["error_code"] == "invalid_link_payload"


class TestHandleGetTaskLinks:
    """AG3-105/AC4: GET /task-links hydrates outgoing links from backend truth."""

    def test_list_task_links_empty(self, routes: TaskManagementRoutes) -> None:
        resp = routes.handle_get(f"/v1/projects/{_PROJ}/task-links", {}, _CORR)
        assert resp is not None
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["links"] == []
        assert body["project_key"] == _PROJ

    def test_list_task_links_after_link(self, routes: TaskManagementRoutes) -> None:
        c1 = routes.handle_post(f"/v1/projects/{_PROJ}/tasks", _task_payload(title="Source"), _CORR)
        c2 = routes.handle_post(f"/v1/projects/{_PROJ}/tasks", _task_payload(title="Target"), _CORR)
        assert c1 is not None and c2 is not None
        id1 = json.loads(c1.body)["task"]["task_id"]
        id2 = json.loads(c2.body)["task"]["task_id"]
        link_resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{id1}/links",
            {"target_kind": "task", "target_id": id2, "kind": "relates_to"},
            _CORR,
        )
        assert link_resp is not None and link_resp.status_code == 201

        resp = routes.handle_get(f"/v1/projects/{_PROJ}/task-links", {}, _CORR)
        assert resp is not None
        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["links"] == [
            {
                "project_key": _PROJ,
                "task_id": id1,
                "target_kind": "task",
                "target_id": id2,
                "kind": "relates_to",
            }
        ]

    def test_task_links_path_not_captured_by_other_routes(
        self, routes: TaskManagementRoutes
    ) -> None:
        # /task-links must be its own route, not shadowed by /tasks/{task_id}.
        resp = routes.handle_get(f"/v1/projects/{_PROJ}/task-links", {}, _CORR)
        assert resp is not None
        assert "links" in json.loads(resp.body)

    def test_list_task_links_tenant_isolation(self, routes: TaskManagementRoutes) -> None:
        # Two projects, identical task ids — link reads stay partitioned (AC6).
        a1 = routes.handle_post("/v1/projects/PROJ-A/tasks", _task_payload(title="A1"), _CORR)
        a2 = routes.handle_post("/v1/projects/PROJ-A/tasks", _task_payload(title="A2"), _CORR)
        b1 = routes.handle_post("/v1/projects/PROJ-B/tasks", _task_payload(title="B1"), _CORR)
        b2 = routes.handle_post("/v1/projects/PROJ-B/tasks", _task_payload(title="B2"), _CORR)
        assert a1 and a2 and b1 and b2
        a1_id = json.loads(a1.body)["task"]["task_id"]
        a2_id = json.loads(a2.body)["task"]["task_id"]
        b1_id = json.loads(b1.body)["task"]["task_id"]
        b2_id = json.loads(b2.body)["task"]["task_id"]
        routes.handle_post(
            f"/v1/projects/PROJ-A/tasks/{a1_id}/links",
            {"target_kind": "task", "target_id": a2_id, "kind": "relates_to"},
            _CORR,
        )
        routes.handle_post(
            f"/v1/projects/PROJ-B/tasks/{b1_id}/links",
            {"target_kind": "task", "target_id": b2_id, "kind": "duplicate_of"},
            _CORR,
        )

        list_a = routes.handle_get("/v1/projects/PROJ-A/task-links", {}, _CORR)
        list_b = routes.handle_get("/v1/projects/PROJ-B/task-links", {}, _CORR)
        assert list_a is not None and list_b is not None
        links_a = json.loads(list_a.body)["links"]
        links_b = json.loads(list_b.body)["links"]
        assert len(links_a) == 1
        assert links_a[0]["project_key"] == "PROJ-A"
        assert links_a[0]["target_id"] == a2_id
        assert len(links_b) == 1
        assert links_b[0]["project_key"] == "PROJ-B"
        assert links_b[0]["target_id"] == b2_id

    def test_list_task_links_unexpected_exception_returns_500(
        self, routes: TaskManagementRoutes
    ) -> None:
        assert routes.task_management is not None
        with patch.object(routes.task_management, "list_task_links", side_effect=RuntimeError("boom")):
            resp = routes.handle_get(f"/v1/projects/{_PROJ}/task-links", {}, _CORR)
        assert resp is not None
        assert resp.status_code == 500
        assert json.loads(resp.body)["error_code"] == "internal_error"

    def test_list_task_links_unavailable_returns_503(self) -> None:
        resp = TaskManagementRoutes().handle_get("/v1/projects/PROJ/task-links", {}, _CORR)
        assert resp is not None
        assert resp.status_code == 503
        assert json.loads(resp.body)["error_code"] == "task_management_unavailable"


class TestHandleDelete:
    def test_handle_delete_returns_none(self, routes: TaskManagementRoutes) -> None:
        """handle_delete always returns None (no DELETE endpoints)."""
        result = routes.handle_delete(
            "/v1/projects/PROJ/tasks/TM-2026-0001", "corr-id"
        )
        assert result is None

    def test_unavailable_returns_503(self) -> None:
        """TaskManagementRoutes() with no service returns 503 on any call (finding 8)."""
        no_service_routes = TaskManagementRoutes()
        resp = no_service_routes.handle_get(
            "/v1/projects/PROJ/tasks", {}, "corr-id"
        )
        assert resp is not None
        assert resp.status_code == 503
        body = json.loads(resp.body)
        assert body["error_code"] == "task_management_unavailable"

    def test_unavailable_post_returns_503(self) -> None:
        """POST with no service returns 503 (not 500), finding 8."""
        no_service_routes = TaskManagementRoutes()
        resp = no_service_routes.handle_post(
            "/v1/projects/PROJ/tasks",
            _task_payload(),
            "corr-id",
        )
        assert resp is not None
        assert resp.status_code == 503


class TestInternalError500VsUnavailable503:
    """Finding 8: unexpected exceptions -> 500 internal_error, not 503 unavailable."""

    def test_unexpected_exception_in_list_tasks_returns_500(
        self, routes: TaskManagementRoutes
    ) -> None:
        """Unexpected exception in list_tasks returns 500 (not 503)."""
        assert routes.task_management is not None
        with patch.object(routes.task_management, "list_tasks", side_effect=RuntimeError("boom")):
            resp = routes.handle_get(f"/v1/projects/{_PROJ}/tasks", {}, _CORR)
        assert resp is not None
        assert resp.status_code == 500
        body = json.loads(resp.body)
        assert body["error_code"] == "internal_error"

    def test_unexpected_exception_in_get_task_returns_500(
        self, routes: TaskManagementRoutes
    ) -> None:
        """Unexpected exception in get_task returns 500 (not 503)."""
        assert routes.task_management is not None
        with patch.object(routes.task_management, "get_task", side_effect=RuntimeError("db gone")):
            resp = routes.handle_get(f"/v1/projects/{_PROJ}/tasks/TM-2026-0001", {}, _CORR)
        assert resp is not None
        assert resp.status_code == 500
        body = json.loads(resp.body)
        assert body["error_code"] == "internal_error"

    def test_unexpected_exception_in_resolve_task_returns_500(
        self, routes: TaskManagementRoutes
    ) -> None:
        """Unexpected exception in resolve_task returns 500 (not 503)."""
        assert routes.task_management is not None
        with patch.object(routes.task_management, "resolve_task", side_effect=RuntimeError("crash")):
            resp = routes.handle_post(
                f"/v1/projects/{_PROJ}/tasks/TM-2026-0001/resolve",
                {"resolved_by": "human"},
                _CORR,
            )
        assert resp is not None
        assert resp.status_code == 500
        body = json.loads(resp.body)
        assert body["error_code"] == "internal_error"

    def test_service_none_still_returns_503_not_500(self) -> None:
        """service=None returns 503, not 500 (genuine unavailability)."""
        routes = TaskManagementRoutes()
        resp = routes.handle_get("/v1/projects/PROJ/tasks", {}, "corr")
        assert resp is not None
        assert resp.status_code == 503
        body = json.loads(resp.body)
        assert body["error_code"] == "task_management_unavailable"
