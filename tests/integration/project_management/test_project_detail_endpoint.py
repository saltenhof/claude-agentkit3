"""Integration test: GET /v1/projects/{key} returns the project_detail view.

Drives the real control-plane HTTP dispatcher with real state-backend
(SQLite) persistence for both the Project entity and the
story_context_manager Story corpus, then asserts the flat
``project_detail`` wire shape (AG3-040 sub-block a).

No mocks: real ``StateBackendProjectRepository`` /
``StateBackendStoryRepository`` / ``StoryService`` /
``ProjectDetailService`` against a ``tmp_path``-scoped SQLite DB.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.http import ControlPlaneApplication
from agentkit.backend.control_plane_http.app import ControlPlaneApplicationRoutes
from agentkit.backend.core_types import StoryDependencyKind
from agentkit.backend.execution_planning.entities import StoryDependency
from agentkit.backend.project_management.entities import ProjectConfiguration
from agentkit.backend.project_management.http.routes import (
    ProjectManagementRoutes,
    _no_repos_in_use,
)
from agentkit.backend.project_management.lifecycle import create_project
from agentkit.backend.project_management.service import ProjectDetailService
from agentkit.backend.state_backend.store import facade
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.backend.state_backend.store.story_dependency_repository import (
    StateBackendStoryDependencyRepository,
)
from agentkit.backend.state_backend.store.story_repository import (
    StateBackendIdempotencyKeyRepository,
    StateBackendStoryRepository,
)
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import CreateStoryInput

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pin SQLite for this tmp_path-scoped integration test.  Other suites
    # (e.g. contract/state_backend) install a session-scoped postgres env;
    # without this pin a leaked AGENTKIT_STATE_BACKEND=postgres would route
    # our repositories to the shared Postgres DB instead of tmp_path.
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    facade.reset_backend_cache_for_tests()


def _story_service(tmp_path: Path) -> StoryService:
    return StoryService(
        story_repository=StateBackendStoryRepository(tmp_path),
        project_repository=StateBackendProjectRepository(tmp_path),
        idempotency_repository=StateBackendIdempotencyKeyRepository(tmp_path),
        dependency_repository=StateBackendStoryDependencyRepository(tmp_path),
        event_emitter=lambda *_: None,
    )


def _app(tmp_path: Path) -> ControlPlaneApplication:
    project_repo = StateBackendProjectRepository(tmp_path)
    detail_service = ProjectDetailService(
        project_repository=project_repo,
        story_service=_story_service(tmp_path),
    )
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=ProjectManagementRoutes(
                repository=project_repo,
                repos_in_use_checker=_no_repos_in_use,
                detail_service=detail_service,
            ),
        ),
    )


def _seed_project(tmp_path: Path) -> None:
    repo = StateBackendProjectRepository(tmp_path)
    config = ProjectConfiguration(
        repo_url="",
        default_branch="main",
        default_worker_count=2,
        repositories=["repo-a"],
    )
    repo.save(
        create_project("tenant-a", "Tenant A", "AG3", config, repositories=["repo-a"]),
    )


def test_get_project_detail_returns_flat_wire_view(tmp_path: Path) -> None:
    _seed_project(tmp_path)

    # Create two stories: one stays in Backlog, one is approved.
    service = _story_service(tmp_path)
    backlog = service.create_story(
        CreateStoryInput(project_key="tenant-a", title="Backlog story", type="implementation", repos=["repo-a"]),
        op_id="op-1",
    )
    approved = service.create_story(
        CreateStoryInput(project_key="tenant-a", title="Approved story", type="implementation", repos=["repo-a"]),
        op_id="op-2",
    )
    service.approve_story(approved.story_display_id, op_id="op-3")

    response = _app(tmp_path).handle_request(
        method="GET",
        path="/v1/projects/tenant-a",
        body=b"",
        request_headers={"X-Correlation-Id": "req-detail"},
    )

    assert response.status_code == HTTPStatus.OK
    body = json.loads(response.body.decode("utf-8"))
    detail = body["project"]
    assert detail == {
        "project_key": "tenant-a",
        "display_name": "Tenant A",
        "status": "active",
        "mode_lock": {"project_key": "tenant-a", "mode": "idle"},
        "story_counters": {
            "project_key": "tenant-a",
            "total": 2,
            "finished": 0,
            "running": 0,
            "ready": 1,  # the approved story has no blocker / deps
            "queue": 1,  # one Approved
            "blocked": 1,  # the Backlog story
        },
        "concept_anchors": [],
    }
    _ = backlog  # created for the corpus; asserted via counters


def test_counters_classify_persisted_dependency_as_blocked(tmp_path: Path) -> None:
    """Regression (codex-a-r1 BLOCK): a persisted, NON-Done dependency edge
    must move an Approved story from ``ready`` to ``blocked`` through the real
    state-backend read path.

    Seeds two Approved stories where B depends on A (A not Done) with a real
    ``StateBackendStoryDependencyRepository`` edge.  Before the fix, the
    production read path returned ``Story.dependencies == []`` (the join was
    never materialized), so B was wrongly counted ``ready``.  After A
    completes, B becomes ``ready``.
    """
    _seed_project(tmp_path)
    service = _story_service(tmp_path)

    story_a = service.create_story(
        CreateStoryInput(
            project_key="tenant-a", title="Predecessor A",
            type="implementation", repos=["repo-a"],
        ),
        op_id="dep-op-a",
    )
    story_b = service.create_story(
        CreateStoryInput(
            project_key="tenant-a", title="Dependent B",
            type="implementation", repos=["repo-a"],
        ),
        op_id="dep-op-b",
    )
    service.approve_story(story_a.story_display_id, op_id="dep-op-approve-a")
    service.approve_story(story_b.story_display_id, op_id="dep-op-approve-b")

    # AG3-050: the dependency store FK-references the STATIC ``stories``
    # stammdaten (``stories.story_display_id``), satisfied above by
    # ``create_story``.  No ``story_contexts`` runtime rows are seeded: both the
    # counters join (``list_stories_with_dependencies``) and the dependency edge
    # below resolve against the static stories + dependency store, so the
    # unified static identity (A1) is exercised without a runtime snapshot.

    # Persist a REAL dependency edge B -> A through the dependency store.
    dep_repo = StateBackendStoryDependencyRepository(tmp_path)
    dep_repo.add(
        StoryDependency(
            story_id=story_b.story_display_id,
            depends_on_story_id=story_a.story_display_id,
            kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            created_at=datetime.now(UTC),
        ),
        project_key="tenant-a",
    )

    def _counters() -> dict[str, int]:
        response = _app(tmp_path).handle_request(
            method="GET",
            path="/v1/projects/tenant-a",
            body=b"",
            request_headers={"X-Correlation-Id": "req-dep"},
        )
        assert response.status_code == HTTPStatus.OK
        body = json.loads(response.body.decode("utf-8"))
        return body["project"]["story_counters"]

    # A is Approved+ready, B is Approved but blocked by the open dependency.
    before = _counters()
    assert before["queue"] == 2  # both Approved
    assert before["ready"] == 1  # only A
    assert before["blocked"] == 1  # B blocked by open dependency A

    # Complete A; B's only dependency is now Done -> B becomes ready.
    service.begin_progress(story_a.story_display_id)
    service.complete_story(story_a.story_display_id)

    after = _counters()
    assert after["finished"] == 1  # A Done
    assert after["queue"] == 1  # only B Approved
    assert after["ready"] == 1  # B now ready
    assert after["blocked"] == 0


def test_get_missing_project_detail_returns_404(tmp_path: Path) -> None:
    response = _app(tmp_path).handle_request(
        method="GET",
        path="/v1/projects/missing",
        body=b"",
        request_headers={"X-Correlation-Id": "req-missing"},
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
