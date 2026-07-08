"""Integration test: task-management routes through real ControlPlaneApplication.

Drives POST/GET /v1/projects/{key}/tasks through the REAL productive HTTP entry
ControlPlaneApplication / ControlPlaneApplicationRoutes -- i.e. through the
genuine registration + delegation path.

Proves task routes are reachable end-to-end through the productive app and that
no pipeline mechanics are present in task responses.

Pattern: uses the same in-memory ProjectRepository double + TenantScopeMiddleware
wiring used in test_execution_input_app.py (the canonical integration test pattern
for this codebase).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    ControlPlaneApplicationRoutes,
)
from agentkit.backend.control_plane_http.tenant_scope import TenantScopeMiddleware
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.project_management.lifecycle import create_project
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    InMemoryInflightIdempotencyGuard,
)
from agentkit.backend.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.backend.task_management.http.routes import TaskManagementRoutes
from agentkit.backend.task_management.service import TaskManagement
from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor

_PROJ = "test-proj"
_PROJ_A = "proj-a"
_PROJ_B = "proj-b"

_KNOWN_PROJECTS = frozenset([_PROJ, _PROJ_A, _PROJ_B])


@dataclass
class _ProjectRepo:
    """In-memory project repository double for tenant-scope validation."""

    known_keys: frozenset[str] = field(default_factory=lambda: _KNOWN_PROJECTS)

    def get(self, key: str) -> Project | None:
        if key not in self.known_keys:
            return None
        return create_project(
            key,
            f"Project {key}",
            "AK3",
            ProjectConfiguration(
                repo_url="",
                default_branch="main",
                default_worker_count=1,
                repositories=["repo-a"],
            ),
            repositories=["repo-a"],
        )


class _FakeRoute:
    """Passthrough BC-route stub: never claims a route (returns None for all verbs)."""

    def handle_get(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    def handle_post(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    def handle_put(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    def handle_patch(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    def handle_delete(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None


@pytest.fixture()
def app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ControlPlaneApplication:
    """Real ControlPlaneApplication with task-management routes backed by SQLite."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.setenv("AGENTKIT_STORE_DIR", str(tmp_path))
    reset_backend_cache_for_tests()

    accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
    service = TaskManagement(accessor)
    # Inject a shared first-class in-memory guard: this SQLite-backed test (the
    # control_plane_http subtree is deliberately docker-free, AG3-051) exercises the
    # task routes end-to-end, not idempotency durability, so it uses the guard's
    # documented unit-test path (claim state persists across calls within one test).
    task_routes = TaskManagementRoutes(
        task_management=service,
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
    )
    project_repo = _ProjectRepo()
    fake = _FakeRoute()
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=fake,  # type: ignore[arg-type]
            story_routes=fake,  # type: ignore[arg-type]
            concept_routes=fake,  # type: ignore[arg-type]
            hub_routes=fake,  # type: ignore[arg-type]
            planning_routes=fake,  # type: ignore[arg-type]
            telemetry_routes=fake,  # type: ignore[arg-type]
            auth_routes=fake,  # type: ignore[arg-type]
            kpi_analytics_routes=fake,  # type: ignore[arg-type]
            task_management_routes=task_routes,
        ),
        tenant_scope_middleware=TenantScopeMiddleware(repository=project_repo),  # type: ignore[arg-type]
    )


def _post(app: ControlPlaneApplication, path: str, body: dict) -> dict:
    # Every mutating POST now needs a client-minted op_id (AG3-140 / FK-91 §91.1a
    # Rule 5). Inject a unique one unless the caller already supplied its own.
    body = {"op_id": f"op-{uuid4().hex}", **body}
    resp = app.handle_request(
        method="POST",
        path=path,
        body=json.dumps(body).encode("utf-8"),
        request_headers={"Content-Type": "application/json"},
    )
    return {"status": resp.status_code, "body": json.loads(resp.body)}


def _get(app: ControlPlaneApplication, path: str) -> dict:
    resp = app.handle_request(
        method="GET",
        path=path,
        body=b"",
        request_headers={},
    )
    return {"status": resp.status_code, "body": json.loads(resp.body)}


def _task_payload(**kwargs: object) -> dict:
    """Build create task payload WITHOUT task_id (server-side allocation, finding 9)."""
    base: dict = {
        "kind": "actionable",
        "type": "concept_update",
        "title": "Integration Test Task",
        "body": "Body text",
        "priority": "normal",
        "origin": "human",
    }
    base.update(kwargs)
    # Ensure task_id is NEVER in the payload (server allocates it)
    base.pop("task_id", None)
    return base


class TestTaskRoutesIntegration:
    def test_create_and_read_task(
        self, app: ControlPlaneApplication
    ) -> None:
        """POST /tasks -> 201 with server-allocated task_id; GET /tasks/{id} -> 200."""
        create = _post(app, f"/v1/projects/{_PROJ}/tasks", _task_payload(title="Create and Read"))
        assert create["status"] == 201
        # task_id is server-allocated (TM-YYYY-NNNN)
        task_id = create["body"]["task"]["task_id"]
        assert task_id.startswith("TM-")
        assert create["body"]["task"]["status"] == "open"

        read = _get(app, f"/v1/projects/{_PROJ}/tasks/{task_id}")
        assert read["status"] == 200
        assert read["body"]["task"]["task_id"] == task_id

    def test_create_with_task_id_returns_422(
        self, app: ControlPlaneApplication
    ) -> None:
        """task_id in POST body is rejected with 422 (extra='forbid', finding 9)."""
        bad_payload = {**_task_payload(), "task_id": "TM-2026-0001"}
        resp = _post(app, f"/v1/projects/{_PROJ}/tasks", bad_payload)
        assert resp["status"] == 422
        assert resp["body"]["error_code"] == "invalid_task_payload"

    def test_resolve_task_status_done(
        self, app: ControlPlaneApplication
    ) -> None:
        """POST /tasks/{id}/resolve -> 200, status=done."""
        create = _post(app, f"/v1/projects/{_PROJ}/tasks", _task_payload(title="Resolve Test"))
        task_id = create["body"]["task"]["task_id"]

        resp = _post(
            app,
            f"/v1/projects/{_PROJ}/tasks/{task_id}/resolve",
            {"resolved_by": "human"},
        )
        assert resp["status"] == 200
        assert resp["body"]["task"]["status"] == "done"

    def test_tenant_isolation(
        self, app: ControlPlaneApplication
    ) -> None:
        """Tasks are strictly partitioned by project_key."""
        _post(app, f"/v1/projects/{_PROJ_A}/tasks", _task_payload(title="Task in A"))
        _post(app, f"/v1/projects/{_PROJ_B}/tasks", _task_payload(title="Task in B"))

        list_a = _get(app, f"/v1/projects/{_PROJ_A}/tasks")
        list_b = _get(app, f"/v1/projects/{_PROJ_B}/tasks")

        assert list_a["status"] == 200
        assert list_b["status"] == 200
        assert len(list_a["body"]["tasks"]) == 1
        assert len(list_b["body"]["tasks"]) == 1
        assert list_a["body"]["tasks"][0]["project_key"] == _PROJ_A
        assert list_b["body"]["tasks"][0]["project_key"] == _PROJ_B

    def test_no_pipeline_coupling_in_task_response(
        self, app: ControlPlaneApplication
    ) -> None:
        """Task endpoint response contains no pipeline mechanics (no phases/gates/worktrees)."""
        create = _post(app, f"/v1/projects/{_PROJ}/tasks", _task_payload(title="No Pipeline"))
        task_id = create["body"]["task"]["task_id"]

        resp = _get(app, f"/v1/projects/{_PROJ}/tasks/{task_id}")
        assert resp["status"] == 200
        task_body = resp["body"]["task"]
        # No pipeline mechanics in task response
        assert "phases" not in task_body
        assert "gates" not in task_body
        assert "worktree" not in task_body
        assert "phase" not in task_body

    def test_list_tasks_empty_before_create(
        self, app: ControlPlaneApplication
    ) -> None:
        """GET /tasks on empty project returns 200 with empty list."""
        resp = _get(app, f"/v1/projects/{_PROJ}/tasks")
        assert resp["status"] == 200
        assert resp["body"]["tasks"] == []

    def test_task_links_route_reachable_and_tenant_scoped(
        self, app: ControlPlaneApplication
    ) -> None:
        """AG3-105/AC4+AC6: GET /task-links reachable through the real app, tenant-scoped.

        Proves the project-wide link read goes through TenantScopeMiddleware (it is a
        /v1/projects/{key}/... path) and that two projects with identically keyed tasks
        return strictly partitioned link sets — no cross-tenant leak.
        """
        # Source + target task in PROJ-A, then a link between them.
        ca1 = _post(app, f"/v1/projects/{_PROJ_A}/tasks", _task_payload(title="A src"))
        ca2 = _post(app, f"/v1/projects/{_PROJ_A}/tasks", _task_payload(title="A tgt"))
        a_src = ca1["body"]["task"]["task_id"]
        a_tgt = ca2["body"]["task"]["task_id"]
        link_a = _post(
            app,
            f"/v1/projects/{_PROJ_A}/tasks/{a_src}/links",
            {"target_kind": "task", "target_id": a_tgt, "kind": "relates_to"},
        )
        assert link_a["status"] == 201

        # PROJ-B gets its own link.
        cb1 = _post(app, f"/v1/projects/{_PROJ_B}/tasks", _task_payload(title="B src"))
        cb2 = _post(app, f"/v1/projects/{_PROJ_B}/tasks", _task_payload(title="B tgt"))
        b_src = cb1["body"]["task"]["task_id"]
        b_tgt = cb2["body"]["task"]["task_id"]
        _post(
            app,
            f"/v1/projects/{_PROJ_B}/tasks/{b_src}/links",
            {"target_kind": "task", "target_id": b_tgt, "kind": "duplicate_of"},
        )

        links_a = _get(app, f"/v1/projects/{_PROJ_A}/task-links")
        links_b = _get(app, f"/v1/projects/{_PROJ_B}/task-links")
        assert links_a["status"] == 200
        assert links_b["status"] == 200
        assert links_a["body"]["links"] == [
            {
                "project_key": _PROJ_A,
                "task_id": a_src,
                "target_kind": "task",
                "target_id": a_tgt,
                "kind": "relates_to",
            }
        ]
        assert links_b["body"]["links"] == [
            {
                "project_key": _PROJ_B,
                "task_id": b_src,
                "target_kind": "task",
                "target_id": b_tgt,
                "kind": "duplicate_of",
            }
        ]

    def test_task_links_unknown_tenant_rejected(
        self, app: ControlPlaneApplication
    ) -> None:
        """AC6: an unknown project_key on /task-links is rejected by tenant-scope."""
        resp = _get(app, "/v1/projects/unknown-proj/task-links")
        assert resp["status"] in (403, 404)
