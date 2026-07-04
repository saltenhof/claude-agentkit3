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
from uuid import uuid4

import pytest

from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    IdempotencyRequest,
    InMemoryInflightIdempotencyGuard,
)
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
def guard() -> InMemoryInflightIdempotencyGuard:
    """Shared first-class in-memory idempotency guard (NOT a mock).

    The SAME instance is injected into ``routes`` so claim state persists across
    calls within one test (the contract's claim -> mutate -> finalize lifecycle).
    """
    return InMemoryInflightIdempotencyGuard()


@pytest.fixture()
def routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    guard: InMemoryInflightIdempotencyGuard,
) -> Iterator[TaskManagementRoutes]:
    """Real TaskManagementRoutes backed by SQLite in tmp_path.

    An in-memory unified idempotency guard is injected (AG3-140 / FK-91 §91.1a
    Rule 5) so the mutating routes exercise the real claim/replay/mismatch/
    in-flight contract without a database.
    """
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
    service = TaskManagement(accessor)
    yield TaskManagementRoutes(task_management=service, idempotency_guard=guard)
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
    op_id: str | None = None,
) -> dict:
    """Create a task wire payload WITHOUT task_id (server-side allocation, finding 9).

    ``op_id`` is the required idempotency key (AG3-140). It defaults to a fresh
    unique value per call so independent creates never collide; idempotency tests
    pin a fixed ``op_id`` to drive replay/mismatch behaviour.
    """
    payload: dict = {
        "op_id": op_id if op_id is not None else uuid4().hex,
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


def _resolve_body(*, resolved_by: str = "human", op_id: str | None = None) -> dict:
    """Wire body for resolve/dismiss with a required op_id (fresh unique default)."""
    return {
        "op_id": op_id if op_id is not None else uuid4().hex,
        "resolved_by": resolved_by,
    }


def _link_body(
    *,
    target_kind: str,
    target_id: str,
    kind: str = "relates_to",
    op_id: str | None = None,
) -> dict:
    """Wire body for link/unlink with a required op_id (fresh unique default)."""
    return {
        "op_id": op_id if op_id is not None else uuid4().hex,
        "target_kind": target_kind,
        "target_id": target_id,
        "kind": kind,
    }


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
            _resolve_body(resolved_by="human"),
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
            _resolve_body(resolved_by="agent"),
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
            _resolve_body(resolved_by="human"),
            _CORR,
        )
        assert r1 is not None
        assert json.loads(r1.body)["task"]["status"] == "done"

        r2 = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{id2}/dismiss",
            _resolve_body(resolved_by="human"),
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
            _link_body(target_kind="task", target_id=id2, kind="relates_to"),
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
            _link_body(target_kind="story", target_id="AG3-001", kind="relates_to"),
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
            _link_body(target_kind="artifact", target_id="some-artifact", kind="relates_to"),
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
            _link_body(target_kind="task", target_id=id2, kind="relates_to"),
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
            _link_body(target_kind="task", target_id=a2_id, kind="relates_to"),
            _CORR,
        )
        routes.handle_post(
            f"/v1/projects/PROJ-B/tasks/{b1_id}/links",
            _link_body(target_kind="task", target_id=b2_id, kind="duplicate_of"),
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
                _resolve_body(resolved_by="human"),
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


# ---------------------------------------------------------------------------
# AG3-140 / FK-91 §91.1a Rule 5 — unified idempotency contract on the 5
# mutating POST routes (create, resolve, dismiss, link, unlink).
# ---------------------------------------------------------------------------


def _create_task(
    routes: TaskManagementRoutes,
    *,
    project_key: str = _PROJ,
    title: str = "Task",
    op_id: str | None = None,
) -> str:
    """Create a task through the route and return its server-allocated id."""
    resp = routes.handle_post(
        f"/v1/projects/{project_key}/tasks",
        _task_payload(title=title, op_id=op_id),
        _CORR,
    )
    assert resp is not None and resp.status_code == 201, resp
    return json.loads(resp.body)["task"]["task_id"]


def _preclaim(
    guard: InMemoryInflightIdempotencyGuard,
    *,
    op_id: str,
    operation_kind: str,
    project_key: str = _PROJ,
) -> None:
    """Leave a live ``claimed`` row for ``op_id`` (models a concurrent caller)."""
    guard.claim(
        IdempotencyRequest(
            op_id=op_id,
            operation_kind=operation_kind,
            body_hash="preclaimed-hash",
            project_key=project_key,
            story_id=None,
            correlation_id=_CORR,
        )
    )


class TestCreateIdempotency:
    def test_create_missing_op_id_returns_422_missing_op_id(
        self, routes: TaskManagementRoutes
    ) -> None:
        payload = _task_payload(title="No op_id")
        del payload["op_id"]
        resp = routes.handle_post(f"/v1/projects/{_PROJ}/tasks", payload, _CORR)
        assert resp is not None
        assert resp.status_code == 422
        assert json.loads(resp.body)["error_code"] == "missing_op_id"

    def test_create_replay_returns_stored_result_and_runs_once(
        self, routes: TaskManagementRoutes
    ) -> None:
        payload = _task_payload(title="Replay Create", op_id="op-create-replay")
        first = routes.handle_post(f"/v1/projects/{_PROJ}/tasks", payload, _CORR)
        second = routes.handle_post(f"/v1/projects/{_PROJ}/tasks", payload, _CORR)
        assert first is not None and second is not None
        assert first.status_code == 201 and second.status_code == 201
        # Byte-for-byte identical stored result on replay.
        assert first.body == second.body
        id1 = json.loads(first.body)["task"]["task_id"]
        id2 = json.loads(second.body)["task"]["task_id"]
        assert id1 == id2
        # The mutation ran exactly once: a re-execution would allocate a 2nd id.
        listing = routes.handle_get(f"/v1/projects/{_PROJ}/tasks", {}, _CORR)
        assert listing is not None
        assert len(json.loads(listing.body)["tasks"]) == 1

    def test_create_same_op_id_different_body_returns_409_mismatch(
        self, routes: TaskManagementRoutes
    ) -> None:
        first = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks",
            _task_payload(title="Body A", op_id="op-create-mismatch"),
            _CORR,
        )
        assert first is not None and first.status_code == 201
        second = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks",
            _task_payload(title="Body B", op_id="op-create-mismatch"),
            _CORR,
        )
        assert second is not None
        assert second.status_code == 409
        assert json.loads(second.body)["error_code"] == "idempotency_mismatch"

    def test_create_in_flight_returns_409_operation_in_flight(
        self,
        routes: TaskManagementRoutes,
        guard: InMemoryInflightIdempotencyGuard,
    ) -> None:
        _preclaim(guard, op_id="op-create-inflight", operation_kind="task_create")
        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks",
            _task_payload(title="In Flight", op_id="op-create-inflight"),
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 409
        assert json.loads(resp.body)["error_code"] == "operation_in_flight"


class TestResolveIdempotency:
    def test_resolve_missing_op_id_returns_422_missing_op_id(
        self, routes: TaskManagementRoutes
    ) -> None:
        task_id = _create_task(routes, title="Resolve NoOp")
        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/resolve",
            {"resolved_by": "human"},
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 422
        assert json.loads(resp.body)["error_code"] == "missing_op_id"

    def test_resolve_replay_returns_stored_result_without_remutation(
        self, routes: TaskManagementRoutes
    ) -> None:
        task_id = _create_task(routes, title="Resolve Replay")
        body = _resolve_body(resolved_by="human", op_id="op-resolve-replay")
        first = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/resolve", body, _CORR
        )
        second = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/resolve", body, _CORR
        )
        assert first is not None and second is not None
        # Without replay the 2nd resolve of a done task would be 409
        # invalid_task_transition; a replay returns the stored 200 verbatim.
        assert first.status_code == 200 and second.status_code == 200
        assert first.body == second.body
        assert json.loads(second.body)["task"]["status"] == "done"

    def test_resolve_replay_after_failure_returns_stored_404_once(
        self, routes: TaskManagementRoutes
    ) -> None:
        assert routes.task_management is not None
        body = _resolve_body(resolved_by="human", op_id="op-resolve-fail")
        missing = f"/v1/projects/{_PROJ}/tasks/TM-9999-9999/resolve"
        with patch.object(
            routes.task_management,
            "resolve_task",
            wraps=routes.task_management.resolve_task,
        ) as spy:
            first = routes.handle_post(missing, body, _CORR)
            second = routes.handle_post(missing, body, _CORR)
        assert first is not None and second is not None
        assert first.status_code == 404 and second.status_code == 404
        assert json.loads(second.body)["error_code"] == "task_not_found"
        # The stored deterministic 4xx is replayed — the service ran only once.
        assert spy.call_count == 1

    def test_resolve_same_op_id_different_body_returns_409_mismatch(
        self, routes: TaskManagementRoutes
    ) -> None:
        task_id = _create_task(routes, title="Resolve Mismatch")
        first = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/resolve",
            _resolve_body(resolved_by="human", op_id="op-resolve-mismatch"),
            _CORR,
        )
        assert first is not None and first.status_code == 200
        second = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/resolve",
            _resolve_body(resolved_by="agent", op_id="op-resolve-mismatch"),
            _CORR,
        )
        assert second is not None
        assert second.status_code == 409
        assert json.loads(second.body)["error_code"] == "idempotency_mismatch"

    def test_resolve_same_op_id_different_task_returns_409_mismatch(
        self, routes: TaskManagementRoutes
    ) -> None:
        """AG3-140 hardening: op_id reuse across DIFFERENT tasks (identical body)
        is a fail-closed 409 mismatch, never a silent wrong-task replay.

        The URL-path target task_id is folded into the body-hash, so the same
        op_id + same body against a second task differs in hash -> mismatch.
        """
        task_a = _create_task(routes, title="Resolve Task A")
        task_b = _create_task(routes, title="Resolve Task B")
        body = _resolve_body(resolved_by="human", op_id="op-resolve-crosstask")
        first = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_a}/resolve", body, _CORR
        )
        assert first is not None and first.status_code == 200
        # SAME op_id + SAME body, but a DIFFERENT target task.
        second = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_b}/resolve", body, _CORR
        )
        assert second is not None
        assert second.status_code == 409
        assert json.loads(second.body)["error_code"] == "idempotency_mismatch"
        # Task B was NOT resolved by the wrong-task replay (still open).
        task_b_state = routes.handle_get(
            f"/v1/projects/{_PROJ}/tasks/{task_b}", {}, _CORR
        )
        assert task_b_state is not None
        assert json.loads(task_b_state.body)["task"]["status"] == "open"

    def test_resolve_in_flight_returns_409_operation_in_flight(
        self,
        routes: TaskManagementRoutes,
        guard: InMemoryInflightIdempotencyGuard,
    ) -> None:
        task_id = _create_task(routes, title="Resolve InFlight")
        _preclaim(guard, op_id="op-resolve-inflight", operation_kind="task_resolve")
        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/resolve",
            _resolve_body(resolved_by="human", op_id="op-resolve-inflight"),
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 409
        assert json.loads(resp.body)["error_code"] == "operation_in_flight"


class TestDismissIdempotency:
    def test_dismiss_missing_op_id_returns_422_missing_op_id(
        self, routes: TaskManagementRoutes
    ) -> None:
        task_id = _create_task(routes, title="Dismiss NoOp")
        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/dismiss",
            {"resolved_by": "agent"},
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 422
        assert json.loads(resp.body)["error_code"] == "missing_op_id"

    def test_dismiss_replay_returns_stored_result_without_remutation(
        self, routes: TaskManagementRoutes
    ) -> None:
        task_id = _create_task(routes, title="Dismiss Replay")
        body = _resolve_body(resolved_by="agent", op_id="op-dismiss-replay")
        first = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/dismiss", body, _CORR
        )
        second = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/dismiss", body, _CORR
        )
        assert first is not None and second is not None
        # Re-execution would be 409 invalid_task_transition; replay is stored 200.
        assert first.status_code == 200 and second.status_code == 200
        assert first.body == second.body
        assert json.loads(second.body)["task"]["status"] == "dismissed"

    def test_dismiss_same_op_id_different_body_returns_409_mismatch(
        self, routes: TaskManagementRoutes
    ) -> None:
        task_id = _create_task(routes, title="Dismiss Mismatch")
        first = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/dismiss",
            _resolve_body(resolved_by="human", op_id="op-dismiss-mismatch"),
            _CORR,
        )
        assert first is not None and first.status_code == 200
        second = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/dismiss",
            _resolve_body(resolved_by="agent", op_id="op-dismiss-mismatch"),
            _CORR,
        )
        assert second is not None
        assert second.status_code == 409
        assert json.loads(second.body)["error_code"] == "idempotency_mismatch"

    def test_dismiss_in_flight_returns_409_operation_in_flight(
        self,
        routes: TaskManagementRoutes,
        guard: InMemoryInflightIdempotencyGuard,
    ) -> None:
        task_id = _create_task(routes, title="Dismiss InFlight")
        _preclaim(guard, op_id="op-dismiss-inflight", operation_kind="task_dismiss")
        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/dismiss",
            _resolve_body(resolved_by="agent", op_id="op-dismiss-inflight"),
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 409
        assert json.loads(resp.body)["error_code"] == "operation_in_flight"


class TestLinkIdempotency:
    def test_link_missing_op_id_returns_422_missing_op_id(
        self, routes: TaskManagementRoutes
    ) -> None:
        src = _create_task(routes, title="Link Src")
        tgt = _create_task(routes, title="Link Tgt")
        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{src}/links",
            {"target_kind": "task", "target_id": tgt, "kind": "relates_to"},
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 422
        assert json.loads(resp.body)["error_code"] == "missing_op_id"

    def test_link_replay_returns_stored_result_and_runs_once(
        self, routes: TaskManagementRoutes
    ) -> None:
        assert routes.task_management is not None
        src = _create_task(routes, title="Link Replay Src")
        tgt = _create_task(routes, title="Link Replay Tgt")
        body = _link_body(target_kind="task", target_id=tgt, op_id="op-link-replay")
        path = f"/v1/projects/{_PROJ}/tasks/{src}/links"
        with patch.object(
            routes.task_management,
            "link_task",
            wraps=routes.task_management.link_task,
        ) as spy:
            first = routes.handle_post(path, body, _CORR)
            second = routes.handle_post(path, body, _CORR)
        assert first is not None and second is not None
        assert first.status_code == 201 and second.status_code == 201
        assert first.body == second.body
        # link_task is idempotent at the store, so single-execution is proven by
        # the spy call count (spec-endorsed): the replay never re-enters mutation.
        assert spy.call_count == 1

    def test_link_same_op_id_different_body_returns_409_mismatch(
        self, routes: TaskManagementRoutes
    ) -> None:
        src = _create_task(routes, title="Link Mismatch Src")
        tgt1 = _create_task(routes, title="Link Mismatch Tgt1")
        tgt2 = _create_task(routes, title="Link Mismatch Tgt2")
        path = f"/v1/projects/{_PROJ}/tasks/{src}/links"
        first = routes.handle_post(
            path,
            _link_body(target_kind="task", target_id=tgt1, op_id="op-link-mismatch"),
            _CORR,
        )
        assert first is not None and first.status_code == 201
        second = routes.handle_post(
            path,
            _link_body(target_kind="task", target_id=tgt2, op_id="op-link-mismatch"),
            _CORR,
        )
        assert second is not None
        assert second.status_code == 409
        assert json.loads(second.body)["error_code"] == "idempotency_mismatch"

    def test_link_in_flight_returns_409_operation_in_flight(
        self,
        routes: TaskManagementRoutes,
        guard: InMemoryInflightIdempotencyGuard,
    ) -> None:
        src = _create_task(routes, title="Link InFlight Src")
        tgt = _create_task(routes, title="Link InFlight Tgt")
        _preclaim(guard, op_id="op-link-inflight", operation_kind="task_link")
        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{src}/links",
            _link_body(target_kind="task", target_id=tgt, op_id="op-link-inflight"),
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 409
        assert json.loads(resp.body)["error_code"] == "operation_in_flight"


class TestUnlinkIdempotency:
    def _make_link(
        self, routes: TaskManagementRoutes
    ) -> tuple[str, str]:
        src = _create_task(routes, title="Unlink Src")
        tgt = _create_task(routes, title="Unlink Tgt")
        link = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{src}/links",
            _link_body(target_kind="task", target_id=tgt),
            _CORR,
        )
        assert link is not None and link.status_code == 201
        return src, tgt

    def test_unlink_missing_op_id_returns_422_missing_op_id(
        self, routes: TaskManagementRoutes
    ) -> None:
        src, tgt = self._make_link(routes)
        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{src}/links/delete",
            {"target_kind": "task", "target_id": tgt, "kind": "relates_to"},
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 422
        assert json.loads(resp.body)["error_code"] == "missing_op_id"

    def test_unlink_replay_returns_stored_result_without_remutation(
        self, routes: TaskManagementRoutes
    ) -> None:
        src, tgt = self._make_link(routes)
        body = _link_body(target_kind="task", target_id=tgt, op_id="op-unlink-replay")
        path = f"/v1/projects/{_PROJ}/tasks/{src}/links/delete"
        first = routes.handle_post(path, body, _CORR)
        second = routes.handle_post(path, body, _CORR)
        assert first is not None and second is not None
        # Re-execution would be 404 task_link_not_found (link already removed);
        # replay returns the stored 200 verbatim.
        assert first.status_code == 200 and second.status_code == 200
        assert first.body == second.body

    def test_unlink_same_op_id_different_body_returns_409_mismatch(
        self, routes: TaskManagementRoutes
    ) -> None:
        src, tgt = self._make_link(routes)
        tgt2 = _create_task(routes, title="Unlink Tgt2")
        link2 = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{src}/links",
            _link_body(target_kind="task", target_id=tgt2),
            _CORR,
        )
        assert link2 is not None and link2.status_code == 201
        path = f"/v1/projects/{_PROJ}/tasks/{src}/links/delete"
        first = routes.handle_post(
            path,
            _link_body(target_kind="task", target_id=tgt, op_id="op-unlink-mismatch"),
            _CORR,
        )
        assert first is not None and first.status_code == 200
        second = routes.handle_post(
            path,
            _link_body(target_kind="task", target_id=tgt2, op_id="op-unlink-mismatch"),
            _CORR,
        )
        assert second is not None
        assert second.status_code == 409
        assert json.loads(second.body)["error_code"] == "idempotency_mismatch"

    def test_unlink_in_flight_returns_409_operation_in_flight(
        self,
        routes: TaskManagementRoutes,
        guard: InMemoryInflightIdempotencyGuard,
    ) -> None:
        src, tgt = self._make_link(routes)
        _preclaim(guard, op_id="op-unlink-inflight", operation_kind="task_unlink")
        resp = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{src}/links/delete",
            _link_body(target_kind="task", target_id=tgt, op_id="op-unlink-inflight"),
            _CORR,
        )
        assert resp is not None
        assert resp.status_code == 409
        assert json.loads(resp.body)["error_code"] == "operation_in_flight"


class TestCrossActionRejection:
    """Codex r4 #1: op_id reuse across a DIFFERENT action (identical body-hash) is
    a fail-closed 409, never a cross-action replay; the second action never runs."""

    def test_resolve_then_dismiss_same_op_id_returns_409_not_replay(
        self, routes: TaskManagementRoutes
    ) -> None:
        task_id = _create_task(routes, title="Cross Resolve/Dismiss")
        body = _resolve_body(resolved_by="human", op_id="op-cross-rd")
        resolved = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/resolve", body, _CORR
        )
        assert resolved is not None and resolved.status_code == 200

        # SAME op_id + structurally-identical body, DIFFERENT action.
        dismissed = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{task_id}/dismiss", dict(body), _CORR
        )
        assert dismissed is not None
        assert dismissed.status_code == 409
        assert json.loads(dismissed.body)["error_code"] == "idempotency_mismatch"

        # The dismiss did NOT run -- the task is still resolved ('done'), never
        # a replay of the stored resolve response as a dismiss.
        state = routes.handle_get(f"/v1/projects/{_PROJ}/tasks/{task_id}", {}, _CORR)
        assert state is not None
        assert json.loads(state.body)["task"]["status"] == "done"

    def test_link_then_unlink_same_op_id_returns_409_not_replay(
        self, routes: TaskManagementRoutes
    ) -> None:
        src = _create_task(routes, title="Cross Link/Unlink Src")
        tgt = _create_task(routes, title="Cross Link/Unlink Tgt")
        body = _link_body(target_kind="task", target_id=tgt, op_id="op-cross-lu")
        linked = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{src}/links", body, _CORR
        )
        assert linked is not None and linked.status_code == 201

        # SAME op_id + identical body, DIFFERENT action (unlink).
        unlinked = routes.handle_post(
            f"/v1/projects/{_PROJ}/tasks/{src}/links/delete", dict(body), _CORR
        )
        assert unlinked is not None
        assert unlinked.status_code == 409
        assert json.loads(unlinked.body)["error_code"] == "idempotency_mismatch"

        # The unlink did NOT run -- the link still exists.
        links = routes.handle_get(f"/v1/projects/{_PROJ}/task-links", {}, _CORR)
        assert links is not None
        assert len(json.loads(links.body)["links"]) == 1
