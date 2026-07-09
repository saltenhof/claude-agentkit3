"""Integration tests: AG3-091 six project-scoped read-model GET endpoints.

Drives the real control-plane HTTP dispatcher with real state-backend
(SQLite) persistence. No mocks used except for the event_emitter callback
which is side-effect-only.

Endpoints under test:
  GET /v1/projects/{key}/execution-input/limits
  GET /v1/projects/{key}/mode-lock
  GET /v1/projects/{key}/stories/counters
  GET /v1/projects/{key}/stories/{story_id}/flow
  GET /v1/projects/{key}/coverage/stories/{story_id}/acceptance
  GET /v1/projects/{key}/coverage/stories/{story_id}/are-evidence
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.http import ControlPlaneApplication
from agentkit.backend.control_plane_http.app import ControlPlaneApplicationRoutes
from agentkit.backend.control_plane_http.tenant_scope import TenantScopeMiddleware
from agentkit.backend.execution_planning.entities import ParallelizationConfig
from agentkit.backend.project_management.entities import ProjectConfiguration
from agentkit.backend.project_management.http.routes import (
    ProjectManagementRoutes,
    _no_repos_in_use,
)
from agentkit.backend.project_management.lifecycle import create_project
from agentkit.backend.project_management.read_model_routes import ReadModelRoutes
from agentkit.backend.project_management.service import ProjectDetailService
from agentkit.backend.requirements_coverage.models import StoryAreLink, StoryAreLinkKind
from agentkit.backend.state_backend.persistence_test_support import (
    reset_backend_cache_for_tests,
)
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    InMemoryInflightIdempotencyGuard,
)
from agentkit.backend.state_backend.store.parallelization_config_repository import (
    StateBackendParallelizationConfigRepository,
)
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.backend.state_backend.store.story_are_link_repository import (
    StateBackendStoryAreLinkRepository,
)
from agentkit.backend.state_backend.store.story_context_repository import (
    StateBackendStoryContextRepository,
)
from agentkit.backend.state_backend.store.story_repository import (
    StateBackendStoryRepository,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import CreateStoryInput, Story
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()


def _story_service(tmp_path: Path) -> StoryService:
    from agentkit.backend.state_backend.store.story_dependency_repository import (
        StateBackendStoryDependencyRepository,
    )

    return StoryService(
        story_repository=StateBackendStoryRepository(tmp_path),
        project_repository=StateBackendProjectRepository(tmp_path),
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        dependency_repository=StateBackendStoryDependencyRepository(tmp_path),
        event_emitter=lambda *_: None,
    )


def _app(tmp_path: Path) -> ControlPlaneApplication:
    project_repo = StateBackendProjectRepository(tmp_path)
    story_svc = _story_service(tmp_path)
    config_repo = StateBackendParallelizationConfigRepository(tmp_path)
    are_repo = StateBackendStoryAreLinkRepository(tmp_path)
    detail_service = ProjectDetailService(
        project_repository=project_repo,
        story_service=story_svc,
    )
    # Inject the tmp_path-scoped project repo into TenantScopeMiddleware so
    # that project existence checks in the middleware resolve against the same
    # SQLite file used by the test fixtures.
    tenant_scope = TenantScopeMiddleware(repository=project_repo)
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=ProjectManagementRoutes(
                repository=project_repo,
                repos_in_use_checker=_no_repos_in_use,
                detail_service=detail_service,
            ),
            read_model_routes=ReadModelRoutes(
                project_repository=project_repo,
                story_service=story_svc,
                config_repository=config_repo,
                are_link_repository=are_repo,
            ),
        ),
        tenant_scope_middleware=tenant_scope,
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


def _seed_story_context(tmp_path: Path, story: Story) -> None:
    """Seed a story_contexts row needed for story_are_links FK (AG3-050).

    The ``story_are_links`` FK references ``story_contexts(story_id)``
    (the display ID), NOT the static ``stories`` stammdaten. Without this
    seed the ARE-link INSERT fails with FOREIGN KEY constraint error.
    """
    ctx_repo = StateBackendStoryContextRepository(tmp_path)
    ctx_repo.save(
        StoryContext(
            project_key=story.project_key,
            story_number=story.story_number,
            story_id=story.story_display_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            title=story.title,
            created_at=datetime.now(UTC),
        ),
    )


def _seed_project_b(tmp_path: Path) -> None:
    """Seed a second project 'tenant-b' for cross-project scope tests (ERROR D).

    Uses a distinct story-id prefix "TB" to avoid prefix conflicts with
    'tenant-a' which uses 'AG3'.
    """
    repo = StateBackendProjectRepository(tmp_path)
    config = ProjectConfiguration(
        repo_url="",
        default_branch="main",
        default_worker_count=1,
        repositories=["repo-b"],
    )
    repo.save(
        create_project("tenant-b", "Tenant B", "TB", config, repositories=["repo-b"]),
    )


def _get(app: ControlPlaneApplication, path: str) -> tuple[int, object]:
    response = app.handle_request(
        method="GET",
        path=path,
        body=b"",
        request_headers={"X-Correlation-Id": "req-test"},
    )
    return response.status_code, json.loads(response.body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Execution limits
# ---------------------------------------------------------------------------


def test_execution_limits_unknown_project_returns_404(tmp_path: Path) -> None:
    app = _app(tmp_path)
    status, _ = _get(app, "/v1/projects/missing/execution-input/limits")
    assert status == HTTPStatus.NOT_FOUND


def test_execution_limits_no_config_returns_zeros(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    app = _app(tmp_path)
    status, body = _get(app, "/v1/projects/tenant-a/execution-input/limits")
    assert status == HTTPStatus.OK
    limits = body["execution_limits"]  # type: ignore[index]
    assert limits["project_key"] == "tenant-a"
    assert limits["repo_parallel_cap"] == 0
    assert limits["merge_risk_cap"] == 0
    assert limits["max_parallel_agent_cap"] == 0
    assert limits["llm_pool_cap"] == 0
    assert limits["ci_capacity_cap"] == 0


def test_execution_limits_with_config(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    config = ParallelizationConfig(
        project_key="tenant-a",
        max_parallel_stories=4,
        max_parallel_stories_per_repo=2,
    )
    StateBackendParallelizationConfigRepository(tmp_path).upsert(config)

    app = _app(tmp_path)
    status, body = _get(app, "/v1/projects/tenant-a/execution-input/limits")
    assert status == HTTPStatus.OK
    limits = body["execution_limits"]  # type: ignore[index]
    assert limits["repo_parallel_cap"] == 2
    assert limits["merge_risk_cap"] == 4


# ---------------------------------------------------------------------------
# Mode-lock
# ---------------------------------------------------------------------------


def test_mode_lock_unknown_project_returns_404(tmp_path: Path) -> None:
    app = _app(tmp_path)
    status, _ = _get(app, "/v1/projects/missing/mode-lock")
    assert status == HTTPStatus.NOT_FOUND


def test_mode_lock_no_stories_is_idle(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    app = _app(tmp_path)
    status, body = _get(app, "/v1/projects/tenant-a/mode-lock")
    assert status == HTTPStatus.OK
    assert body["mode_lock"] == {"project_key": "tenant-a", "mode": "idle"}  # type: ignore[index]


def test_mode_lock_in_progress_story_is_standard(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(project_key="tenant-a", title="S1", type="implementation", repos=["repo-a"]),
        op_id="op-1",
    )
    svc.approve_story(story.story_display_id, op_id="op-2")
    svc.begin_progress(story.story_display_id)

    app = _app(tmp_path)
    status, body = _get(app, "/v1/projects/tenant-a/mode-lock")
    assert status == HTTPStatus.OK
    assert body["mode_lock"]["mode"] == "standard"  # type: ignore[index]


def test_mode_lock_in_progress_fast_story_is_fast(tmp_path: Path) -> None:
    """MAJOR AC2: fast-mode story In Progress -> mode-lock returns mode='fast'.

    Proves the fast mode branch of derive_mode_lock (SSOT) is reachable via the
    GET .../mode-lock endpoint without a second computation (AC2, story.md §3 AC2).
    """
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(
            project_key="tenant-a",
            title="Fast mode story",
            type="implementation",
            repos=["repo-a"],
            mode="fast",
        ),
        op_id="op-fast-1",
    )
    svc.approve_story(story.story_display_id, op_id="op-fast-2")
    svc.begin_progress(story.story_display_id)

    app = _app(tmp_path)
    status, body = _get(app, "/v1/projects/tenant-a/mode-lock")
    assert status == HTTPStatus.OK
    assert body["mode_lock"]["mode"] == "fast", (  # type: ignore[index]
        f"Expected mode='fast' for in-progress fast-mode story, "
        f"got {body['mode_lock']['mode']!r}"  # type: ignore[index]
    )
    assert body["mode_lock"]["project_key"] == "tenant-a"  # type: ignore[index]


# ---------------------------------------------------------------------------
# Story counters
# ---------------------------------------------------------------------------


def test_story_counters_unknown_project_returns_404(tmp_path: Path) -> None:
    app = _app(tmp_path)
    status, _ = _get(app, "/v1/projects/missing/stories/counters")
    assert status == HTTPStatus.NOT_FOUND


def test_story_counters_empty_project(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    app = _app(tmp_path)
    status, body = _get(app, "/v1/projects/tenant-a/stories/counters")
    assert status == HTTPStatus.OK
    counters = body["story_counters"]  # type: ignore[index]
    assert counters["total"] == 0
    assert counters["finished"] == 0
    assert counters["running"] == 0
    assert counters["ready"] == 0
    assert counters["queue"] == 0
    assert counters["blocked"] == 0


def test_story_counters_backlog_story_is_blocked(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    svc.create_story(
        CreateStoryInput(project_key="tenant-a", title="B1", type="implementation", repos=["repo-a"]),
        op_id="op-b1",
    )
    app = _app(tmp_path)
    status, body = _get(app, "/v1/projects/tenant-a/stories/counters")
    assert status == HTTPStatus.OK
    counters = body["story_counters"]  # type: ignore[index]
    assert counters["total"] == 1
    assert counters["blocked"] == 1


# ---------------------------------------------------------------------------
# Story flow snapshot
# ---------------------------------------------------------------------------


def test_story_flow_unknown_project_returns_404(tmp_path: Path) -> None:
    app = _app(tmp_path)
    status, _ = _get(app, "/v1/projects/missing/stories/AG3-001/flow")
    assert status == HTTPStatus.NOT_FOUND


def test_story_flow_unknown_story_returns_404(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    app = _app(tmp_path)
    status, _ = _get(app, "/v1/projects/tenant-a/stories/AG3-NONE/flow")
    assert status == HTTPStatus.NOT_FOUND


def test_story_flow_existing_story_returns_snapshot(tmp_path: Path) -> None:
    """Newly created story (Backlog) -> all phases pending with full substep sequences."""
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(project_key="tenant-a", title="Flow story", type="implementation", repos=["repo-a"]),
        op_id="op-flow",
    )
    app = _app(tmp_path)
    status, body = _get(app, f"/v1/projects/tenant-a/stories/{story.story_display_id}/flow")
    assert status == HTTPStatus.OK
    snapshot = body["story_flow_snapshot"]  # type: ignore[index]
    assert snapshot["story_id"] == story.story_display_id
    assert snapshot["mode"] in ("standard", "fast")
    assert len(snapshot["phases"]) == 4
    phase_names = [p["phase"] for p in snapshot["phases"]]
    assert phase_names == ["setup", "exploration", "implementation", "closure"]
    for phase in snapshot["phases"]:
        # Backlog story -> all pending
        assert phase["state"] == "pending", (
            f"Phase {phase['phase']!r} expected pending for Backlog story, "
            f"got {phase['state']!r}"
        )
        # Full substep sequences populated (not empty) for non-fast standard mode.
        assert len(phase["substeps"]) > 0, (
            f"Phase {phase['phase']!r} must have substeps in all-pending initial state"
        )


# ---------------------------------------------------------------------------
# Coverage acceptance
# ---------------------------------------------------------------------------


def test_coverage_acceptance_unknown_project_returns_404(tmp_path: Path) -> None:
    app = _app(tmp_path)
    status, _ = _get(app, "/v1/projects/missing/coverage/stories/AG3-001/acceptance")
    assert status == HTTPStatus.NOT_FOUND


def test_coverage_acceptance_unknown_story_returns_404(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    app = _app(tmp_path)
    status, _ = _get(app, "/v1/projects/tenant-a/coverage/stories/AG3-NONE/acceptance")
    assert status == HTTPStatus.NOT_FOUND


def test_coverage_acceptance_no_links_returns_empty(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(project_key="tenant-a", title="Cov story", type="implementation", repos=["repo-a"]),
        op_id="op-cov",
    )
    app = _app(tmp_path)
    status, body = _get(
        app,
        f"/v1/projects/tenant-a/coverage/stories/{story.story_display_id}/acceptance",
    )
    assert status == HTTPStatus.OK
    acc = body["story_coverage_acceptance"]  # type: ignore[index]
    assert acc["story_id"] == story.story_display_id
    assert acc["project_key"] == "tenant-a"
    assert acc["acceptance_criteria"] == []
    assert acc["linked_requirements"] == []


def test_coverage_acceptance_with_links(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(project_key="tenant-a", title="Linked cov", type="implementation", repos=["repo-a"]),
        op_id="op-linked",
    )
    # story_are_links FK references story_contexts(story_id): seed runtime row first.
    _seed_story_context(tmp_path, story)
    are_repo = StateBackendStoryAreLinkRepository(tmp_path)
    are_repo.add(
        StoryAreLink(
            story_id=story.story_display_id,
            are_item_id="ARE-99",
            kind=StoryAreLinkKind.ADDRESSES,
        )
    )

    app = _app(tmp_path)
    status, body = _get(
        app,
        f"/v1/projects/tenant-a/coverage/stories/{story.story_display_id}/acceptance",
    )
    assert status == HTTPStatus.OK
    acc = body["story_coverage_acceptance"]  # type: ignore[index]
    assert "ARE-99" in acc["linked_requirements"]


# ---------------------------------------------------------------------------
# ARE evidence
# ---------------------------------------------------------------------------


def test_are_evidence_unknown_project_returns_404(tmp_path: Path) -> None:
    app = _app(tmp_path)
    status, _ = _get(app, "/v1/projects/missing/coverage/stories/AG3-001/are-evidence")
    assert status == HTTPStatus.NOT_FOUND


def test_are_evidence_unknown_story_returns_404(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    app = _app(tmp_path)
    status, _ = _get(app, "/v1/projects/tenant-a/coverage/stories/AG3-NONE/are-evidence")
    assert status == HTTPStatus.NOT_FOUND


def test_are_evidence_no_links_returns_empty_list(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(project_key="tenant-a", title="Ev story", type="implementation", repos=["repo-a"]),
        op_id="op-ev",
    )
    app = _app(tmp_path)
    status, body = _get(
        app,
        f"/v1/projects/tenant-a/coverage/stories/{story.story_display_id}/are-evidence",
    )
    assert status == HTTPStatus.OK
    evidence = body["story_are_evidence"]  # type: ignore[index]
    assert evidence["linked_requirements"] == []


def test_are_evidence_with_links_and_no_are_url_returns_503(tmp_path: Path) -> None:
    """ERROR 2: links exist but project has no are_url -> FAIL-CLOSED 503.

    When StoryAreLinks exist but the project's ``are_url`` is not configured
    (and no AreClient is injected), the endpoint must return 503 ``are_unavailable``
    instead of silently defaulting coverage_status to ``"linked"`` (fail-open).
    The test project 'tenant-a' has no are_url configured (see _seed_project).
    """
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(project_key="tenant-a", title="Ev linked", type="implementation", repos=["repo-a"]),
        op_id="op-ev-linked",
    )
    # story_are_links FK references story_contexts(story_id): seed runtime row first.
    _seed_story_context(tmp_path, story)
    are_repo = StateBackendStoryAreLinkRepository(tmp_path)
    are_repo.add(
        StoryAreLink(
            story_id=story.story_display_id,
            are_item_id="ARE-55",
            kind=StoryAreLinkKind.PARTIAL,
        )
    )
    # No AreClient injected; project has no are_url -> FAIL-CLOSED 503
    app = _app(tmp_path)
    status, body = _get(
        app,
        f"/v1/projects/tenant-a/coverage/stories/{story.story_display_id}/are-evidence",
    )
    assert status == HTTPStatus.SERVICE_UNAVAILABLE, (
        f"Expected 503 (are_unavailable) when links exist and ARE not configured, got {status}"
    )
    assert body["error_code"] == "are_unavailable"  # type: ignore[index]


# ---------------------------------------------------------------------------
# AC10 / ERROR A: canonical 5-cap derivation from real ParallelizationConfig
# ---------------------------------------------------------------------------


def test_execution_limits_five_caps_from_real_config(tmp_path: Path) -> None:
    """AC10 ERROR A: real ParallelizationConfig -> all 5 caps independently verified.

    Writes a real ParallelizationConfig to the real store and asserts that
    the limits response reflects the canonical derive_budgets fan-out:
    - repo_parallel_cap = max_parallel_stories_per_repo (if set)
    - merge_risk_cap = max_parallel_stories
    - max_parallel_agent_cap = max_parallel_stories (maps api_rate_limit_cap)
    - llm_pool_cap = max_parallel_stories
    - ci_capacity_cap = max_parallel_stories
    """
    _seed_project(tmp_path)
    config = ParallelizationConfig(
        project_key="tenant-a",
        max_parallel_stories=5,
        max_parallel_stories_per_repo=3,
    )
    StateBackendParallelizationConfigRepository(tmp_path).upsert(config)

    app = _app(tmp_path)
    status, body = _get(app, "/v1/projects/tenant-a/execution-input/limits")
    assert status == HTTPStatus.OK
    limits = body["execution_limits"]  # type: ignore[index]
    assert limits["project_key"] == "tenant-a"
    # repo_parallel_cap comes from max_parallel_stories_per_repo
    assert limits["repo_parallel_cap"] == 3
    # all other caps come from max_parallel_stories
    assert limits["merge_risk_cap"] == 5
    assert limits["max_parallel_agent_cap"] == 5  # maps api_rate_limit_cap
    assert limits["llm_pool_cap"] == 5
    assert limits["ci_capacity_cap"] == 5


def test_execution_limits_no_per_repo_cap_falls_back_to_global(tmp_path: Path) -> None:
    """AC10 ERROR A: when max_parallel_stories_per_repo is not set, repo_parallel_cap == max_parallel_stories."""
    _seed_project(tmp_path)
    config = ParallelizationConfig(
        project_key="tenant-a",
        max_parallel_stories=6,
        # no max_parallel_stories_per_repo
    )
    StateBackendParallelizationConfigRepository(tmp_path).upsert(config)

    app = _app(tmp_path)
    status, body = _get(app, "/v1/projects/tenant-a/execution-input/limits")
    assert status == HTTPStatus.OK
    limits = body["execution_limits"]  # type: ignore[index]
    # repo_parallel_cap falls back to global when per-repo not set
    assert limits["repo_parallel_cap"] == 6
    assert limits["merge_risk_cap"] == 6
    assert limits["max_parallel_agent_cap"] == 6
    assert limits["llm_pool_cap"] == 6
    assert limits["ci_capacity_cap"] == 6


# ---------------------------------------------------------------------------
# AC10 / ERROR D: project_key scoping — cross-project story access returns 404
# ---------------------------------------------------------------------------


def test_story_flow_wrong_project_returns_404(tmp_path: Path) -> None:
    """AC10 ERROR D: story of project B requested under project A -> 404 (FK-73 §73.5).

    Uses a shared StoryService (same SQLite backing store) to create a story
    under 'tenant-b'.  The read-model route must reject a cross-project
    story_id lookup and return 404 (no data leak).
    """
    _seed_project(tmp_path)
    _seed_project_b(tmp_path)
    # The same StoryService uses the shared SQLite store (tmp_path).
    svc = _story_service(tmp_path)
    # Create a story under project B (uses TB prefix from _seed_project_b)
    story_b = svc.create_story(
        CreateStoryInput(
            project_key="tenant-b",
            title="B story",
            type="implementation",
            repos=["repo-b"],
        ),
        op_id="op-b-x1",
    )
    app = _app(tmp_path)
    # Request project B's story under project A -> must 404 (no data leak)
    status, _ = _get(
        app,
        f"/v1/projects/tenant-a/stories/{story_b.story_display_id}/flow",
    )
    assert status == HTTPStatus.NOT_FOUND, (
        f"Expected 404 for cross-project story access, got {status}"
    )


def test_coverage_acceptance_wrong_project_returns_404(tmp_path: Path) -> None:
    """AC10 ERROR D: coverage/acceptance of project B story via project A -> 404."""
    _seed_project(tmp_path)
    _seed_project_b(tmp_path)
    svc = _story_service(tmp_path)
    story_b = svc.create_story(
        CreateStoryInput(
            project_key="tenant-b",
            title="B story coverage",
            type="implementation",
            repos=["repo-b"],
        ),
        op_id="op-b-x2",
    )
    app = _app(tmp_path)
    status, _ = _get(
        app,
        f"/v1/projects/tenant-a/coverage/stories/{story_b.story_display_id}/acceptance",
    )
    assert status == HTTPStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# AC10 / ERROR E: 405 for mutation attempts on read-only endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "POST"])
def test_limits_mutation_returns_405(
    tmp_path: Path, method: str
) -> None:
    """AC10 ERROR E: PUT/PATCH/DELETE/POST on limits endpoint -> 405 with Allow: GET."""
    _seed_project(tmp_path)
    app = _app(tmp_path)
    response = app.handle_request(
        method=method,
        path="/v1/projects/tenant-a/execution-input/limits",
        body=b"{}",
        request_headers={"X-Correlation-Id": "req-405"},
    )
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    # Allow header must be present
    header_keys = {k.lower() for k, _ in response.headers}
    assert "allow" in header_keys, f"Allow header missing in 405 response (method={method})"
    allow_value = next(v for k, v in response.headers if k.lower() == "allow")
    assert "GET" in allow_value


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "POST"])
def test_coverage_acceptance_mutation_returns_405(
    tmp_path: Path, method: str
) -> None:
    """AC10 ERROR E: mutation on coverage/acceptance -> 405 with Allow: GET."""
    _seed_project(tmp_path)
    app = _app(tmp_path)
    response = app.handle_request(
        method=method,
        path="/v1/projects/tenant-a/coverage/stories/AG3-001/acceptance",
        body=b"{}",
        request_headers={"X-Correlation-Id": "req-405-cov"},
    )
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    header_keys = {k.lower() for k, _ in response.headers}
    assert "allow" in header_keys


# ---------------------------------------------------------------------------
# R5 ERROR 1: 405 fires for EMPTY / NON-JSON mutation bodies (dispatch order)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
@pytest.mark.parametrize("body", [b"", b"not json"])
def test_limits_mutation_405_for_empty_or_non_json_body(
    tmp_path: Path, method: str, body: bytes
) -> None:
    """R5 ERROR 1: empty/non-JSON mutation body on limits -> 405, not 400.

    Drives the REAL ControlPlaneApplication + REAL ReadModelRoutes. The 405
    must fire BEFORE the JSON body decode, so an empty (``b""``) or non-JSON
    (``b"not json"``) body must NOT degrade to ``400 invalid_json``.
    """
    _seed_project(tmp_path)
    app = _app(tmp_path)
    response = app.handle_request(
        method=method,
        path="/v1/projects/tenant-a/execution-input/limits",
        body=body,
        request_headers={"X-Correlation-Id": "req-405-empty"},
    )
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED, (
        f"{method} with body={body!r} must be 405 (read-only), "
        f"got {response.status_code}"
    )
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["error_code"] == "method_not_allowed", (
        f"{method} with body={body!r} must NOT be invalid_json; "
        f"got {payload.get('error_code')!r}"
    )
    allow_value = next(v for k, v in response.headers if k.lower() == "allow")
    assert "GET" in allow_value


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
@pytest.mark.parametrize("body", [b"", b"not json"])
def test_coverage_mutation_405_for_empty_or_non_json_body(
    tmp_path: Path, method: str, body: bytes
) -> None:
    """R5 ERROR 1: empty/non-JSON mutation body on a coverage endpoint -> 405."""
    _seed_project(tmp_path)
    app = _app(tmp_path)
    response = app.handle_request(
        method=method,
        path="/v1/projects/tenant-a/coverage/stories/AG3-001/are-evidence",
        body=body,
        request_headers={"X-Correlation-Id": "req-405-empty-cov"},
    )
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED, (
        f"{method} with body={body!r} must be 405 (read-only), "
        f"got {response.status_code}"
    )
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["error_code"] == "method_not_allowed"


def test_limits_delete_405_with_empty_body(tmp_path: Path) -> None:
    """R5 ERROR 1: DELETE on a read-only path stays 405 (no body decode)."""
    _seed_project(tmp_path)
    app = _app(tmp_path)
    response = app.handle_request(
        method="DELETE",
        path="/v1/projects/tenant-a/execution-input/limits",
        body=b"",
        request_headers={"X-Correlation-Id": "req-405-del"},
    )
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["error_code"] == "method_not_allowed"


# ---------------------------------------------------------------------------
# AC10 / ERROR B: flow fail-closed when project_root set but store broken
# ---------------------------------------------------------------------------


def test_story_flow_all_phases_pending_when_no_phase_state(tmp_path: Path) -> None:
    """AC10 ERROR B: story with no persisted phase_state -> all phases pending with full substeps.

    When a story has not started yet (no row in ``phase_states`` table),
    ``load_phase_state_global`` returns None; the flow renders all 4 phases as
    ``pending`` with full canonical substep sequences.
    This is the EXPECTED initial state, NOT a fail-closed error.
    """
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(
            project_key="tenant-a",
            title="No-root story",
            type="implementation",
            repos=["repo-a"],
        ),
        op_id="op-noroot",
    )
    app = _app(tmp_path)
    status, body = _get(
        app,
        f"/v1/projects/tenant-a/stories/{story.story_display_id}/flow",
    )
    assert status == HTTPStatus.OK
    snapshot = body["story_flow_snapshot"]  # type: ignore[index]
    assert snapshot["story_id"] == story.story_display_id
    phases = snapshot["phases"]
    assert len(phases) == 4
    # All phases must be pending — no phase_state row exists for this story yet.
    for phase in phases:
        assert phase["state"] == "pending", (
            f"Phase {phase['phase']!r} is {phase['state']!r}, expected 'pending'"
        )
        # R3: full substep sequences populated even in all-pending state.
        assert len(phase["substeps"]) > 0, (
            f"Phase {phase['phase']!r} must have substeps even in all-pending state (R3)"
        )


def test_story_flow_active_when_phase_state_persisted(tmp_path: Path) -> None:
    """ERROR 1 + R3: real save_phase_state -> position-based flow derivation.

    Writes a real PhaseState (implementation phase, in_progress) to the SQLite
    backend via ``save_phase_state`` (the canonical write path).  Then GETs the
    flow endpoint and asserts:
    - implementation phase renders as ``active`` (current runtime phase)
    - setup and exploration phases render as ``done`` (position BEFORE implementation)
    - closure phase renders as ``pending`` (position AFTER implementation)

    This validates both:
    (ERROR 1) load_phase_state_global is correctly wired (not always-empty skeleton)
    (R3) position-based derivation: prior phases are done, not pending.
    """
    from tests.phase_state_factory import make_phase_state

    from agentkit.backend.pipeline_engine.phase_executor.models import PhaseStatus
    from agentkit.backend.state_backend.pipeline_runtime_store import save_phase_state

    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(
            project_key="tenant-a",
            title="Phase-state flow story",
            type="implementation",
            repos=["repo-a"],
        ),
        op_id="op-flow-real",
    )
    # Story must be In Progress for position-based derivation to run.
    svc.approve_story(story.story_display_id, op_id="op-approve-flow")
    svc.begin_progress(story.story_display_id)

    # Write a real phase state for the implementation phase.
    # ``save_phase_state`` expects story_dir = the project root (here: tmp_path).
    phase_state = make_phase_state(
        story_id=story.story_display_id,
        phase="implementation",
        status=PhaseStatus.IN_PROGRESS,
    )
    save_phase_state(tmp_path, phase_state)

    # Wire the app with a custom phase_state_loader that passes tmp_path as
    # store_dir so the global lookup targets the same SQLite file written above.
    from agentkit.backend.state_backend.pipeline_runtime_store import load_phase_state_global

    def _phase_loader(sid: str) -> object:
        return load_phase_state_global(sid, tmp_path)

    project_repo = StateBackendProjectRepository(tmp_path)
    story_svc = _story_service(tmp_path)
    config_repo = StateBackendParallelizationConfigRepository(tmp_path)
    are_repo = StateBackendStoryAreLinkRepository(tmp_path)
    detail_service = ProjectDetailService(
        project_repository=project_repo,
        story_service=story_svc,
    )
    tenant_scope = TenantScopeMiddleware(repository=project_repo)
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=ProjectManagementRoutes(
                repository=project_repo,
                repos_in_use_checker=_no_repos_in_use,
                detail_service=detail_service,
            ),
            read_model_routes=ReadModelRoutes(
                project_repository=project_repo,
                story_service=story_svc,
                config_repository=config_repo,
                are_link_repository=are_repo,
                phase_state_loader=_phase_loader,  # route global lookup to tmp_path DB
            ),
        ),
        tenant_scope_middleware=tenant_scope,
    )

    status, body = _get(
        app,
        f"/v1/projects/tenant-a/stories/{story.story_display_id}/flow",
    )
    assert status == HTTPStatus.OK
    snapshot = body["story_flow_snapshot"]  # type: ignore[index]
    phases = {p["phase"]: p for p in snapshot["phases"]}

    # Implementation phase must render as "active" (in_progress -> active).
    assert phases["implementation"]["state"] == "active", (
        "implementation phase must be 'active' after save_phase_state — "
        "all-pending means ERROR 1 (load_phase_state_global not wired)"
    )
    # Prior phases (position BEFORE implementation) -> done (R3 position derivation).
    assert phases["setup"]["state"] == "done", (
        "setup phase must be 'done' when implementation is active (R3 position-based derivation)"
    )
    assert phases["exploration"]["state"] == "done", (
        "exploration phase must be 'done' when implementation is active (R3 position-based derivation)"
    )
    # Later phase (position AFTER implementation) -> pending.
    assert phases["closure"]["state"] == "pending", (
        "closure phase must be 'pending' when implementation is active"
    )
    # Full substep sequences populated for all non-skipped phases.
    assert len(phases["setup"]["substeps"]) > 0
    assert len(phases["implementation"]["substeps"]) > 0
    assert len(phases["closure"]["substeps"]) > 0


def test_story_flow_done_story_all_phases_done(tmp_path: Path) -> None:
    """R3: Done story -> all phases done with full substep sequences."""
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(
            project_key="tenant-a",
            title="Done flow story",
            type="implementation",
            repos=["repo-a"],
        ),
        op_id="op-done-flow",
    )
    # Transition to Done.
    svc.approve_story(story.story_display_id, op_id="op-approve-done")
    svc.begin_progress(story.story_display_id)
    svc.complete_story(story.story_display_id)

    app = _app(tmp_path)
    status, body = _get(
        app,
        f"/v1/projects/tenant-a/stories/{story.story_display_id}/flow",
    )
    assert status == HTTPStatus.OK
    snapshot = body["story_flow_snapshot"]  # type: ignore[index]
    phases = {p["phase"]: p for p in snapshot["phases"]}

    for phase_name in ("setup", "exploration", "implementation", "closure"):
        assert phases[phase_name]["state"] == "done", (
            f"Phase {phase_name!r} must be 'done' for a Done story"
        )
        assert len(phases[phase_name]["substeps"]) > 0, (
            f"Phase {phase_name!r} must have substeps for a Done story"
        )
        for substep in phases[phase_name]["substeps"]:
            assert substep["state"] == "done", (
                f"Substep {substep['substep']!r} in Done story must be 'done'"
            )


# ---------------------------------------------------------------------------
# AC10 / ERROR C: are-evidence uses real StoryAreLink + coverage_status
# ---------------------------------------------------------------------------


def test_are_evidence_with_links_and_no_are_url_returns_503_multi_links(tmp_path: Path) -> None:
    """ERROR 2: multiple links + no are_url -> FAIL-CLOSED 503 (multi-link variant).

    Verifies that FAIL-CLOSED 503 is returned regardless of the number of links
    when the project has no ``are_url`` configured and no AreClient is injected.
    The DB path (StoryAreLink reads from real SQLite) is still exercised.
    """
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(
            project_key="tenant-a",
            title="ARE cov story",
            type="implementation",
            repos=["repo-a"],
        ),
        op_id="op-are-cov",
    )
    _seed_story_context(tmp_path, story)
    are_repo = StateBackendStoryAreLinkRepository(tmp_path)
    are_repo.add(
        StoryAreLink(
            story_id=story.story_display_id,
            are_item_id="ARE-100",
            kind=StoryAreLinkKind.ADDRESSES,
        )
    )
    are_repo.add(
        StoryAreLink(
            story_id=story.story_display_id,
            are_item_id="ARE-200",
            kind=StoryAreLinkKind.PARTIAL,
        )
    )
    # project 'tenant-a' has no are_url -> FAIL-CLOSED 503
    app = _app(tmp_path)
    status, body = _get(
        app,
        f"/v1/projects/tenant-a/coverage/stories/{story.story_display_id}/are-evidence",
    )
    assert status == HTTPStatus.SERVICE_UNAVAILABLE, (
        f"Expected 503 (are_unavailable) when links exist and ARE not configured, got {status}"
    )
    assert body["error_code"] == "are_unavailable"  # type: ignore[index]


def test_are_evidence_coverage_status_with_are_client_fake_transport(tmp_path: Path) -> None:
    """AC10 ERROR C: with AreClient wired via fake transport, coverage_status is enriched.

    The ARE HTTP transport is the ONLY allowed fake boundary (AC10).
    The StoryAreLink and DB path are real.

    Also verifies ERROR 3: evidence_paths is populated from AreClient.list_evidence
    (GET /stories/{id}/evidence) — the fake transport routes by URL suffix.
    """
    from agentkit.backend.requirements_coverage.are_client import AreClient, AreHttpResponse
    from agentkit.backend.requirements_coverage.contract import (
        AreDockpointStatus,
        AreEvidence,
        AreRequirement,
        AreRequirementType,
        CoverageVerdict,
        EvidenceCoverage,
        EvidenceProducer,
        EvidenceType,
    )

    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(
            project_key="tenant-a",
            title="ARE live story",
            type="implementation",
            repos=["repo-a"],
        ),
        op_id="op-are-live",
    )
    _seed_story_context(tmp_path, story)
    are_repo = StateBackendStoryAreLinkRepository(tmp_path)
    are_repo.add(
        StoryAreLink(
            story_id=story.story_display_id,
            are_item_id="ARE-300",
            kind=StoryAreLinkKind.ADDRESSES,
        )
    )
    are_repo.add(
        StoryAreLink(
            story_id=story.story_display_id,
            are_item_id="ARE-400",
            kind=StoryAreLinkKind.RECURRING,
        )
    )

    # Fake CoverageVerdict: ARE-400 is uncovered, ARE-300 is covered.
    uncovered_req = AreRequirement(
        requirement_id="ARE-400",
        requirement_type=AreRequirementType.SYSTEM,
        summary="Uncovered req",
        must_cover=True,
        acceptance_criteria=[],
        recurring=False,
    )
    verdict_payload = CoverageVerdict(
        status=AreDockpointStatus.PASS,
        verdict="FAIL",
        uncovered_requirements=(uncovered_req,),
    )

    # Fake evidence list: ARE-300 has one evidence ref (test locator).
    evidence_item = AreEvidence(
        requirement_id="ARE-300",
        evidence_type=EvidenceType.TEST_REPORT,
        evidence_ref="tests/unit/test_foo.py::test_bar",
        produced_by=EvidenceProducer.WORKER,
        coverage=EvidenceCoverage.FULL,
    )
    evidence_list_payload = [evidence_item.model_dump(mode="json")]

    class _FakeAreTransport:
        """Routes fake ARE responses by URL suffix.

        - GET /stories/{id}/gate -> CoverageVerdict
        - GET /stories/{id}/evidence -> list[AreEvidence]
        """

        def request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str],
            body: bytes | None = None,
        ) -> AreHttpResponse:
            import json as _json

            if url.endswith("/gate"):
                return AreHttpResponse(
                    status_code=200,
                    body=verdict_payload.model_dump_json().encode("utf-8"),
                )
            if url.endswith("/evidence"):
                return AreHttpResponse(
                    status_code=200,
                    body=_json.dumps(evidence_list_payload).encode("utf-8"),
                )
            # Unexpected path -> propagate as HTTP error so tests fail clearly
            return AreHttpResponse(status_code=404, body=b"not found")

    are_client = AreClient(
        base_url="http://fake-are",
        transport=_FakeAreTransport(),
    )

    project_repo = StateBackendProjectRepository(tmp_path)
    story_svc = _story_service(tmp_path)
    config_repo = StateBackendParallelizationConfigRepository(tmp_path)
    detail_service = ProjectDetailService(
        project_repository=project_repo,
        story_service=story_svc,
    )
    tenant_scope = TenantScopeMiddleware(repository=project_repo)
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=ProjectManagementRoutes(
                repository=project_repo,
                repos_in_use_checker=_no_repos_in_use,
                detail_service=detail_service,
            ),
            read_model_routes=ReadModelRoutes(
                project_repository=project_repo,
                story_service=story_svc,
                config_repository=config_repo,
                are_link_repository=are_repo,
                are_client=are_client,  # ARE HTTP fake transport wired here
            ),
        ),
        tenant_scope_middleware=tenant_scope,
    )

    status, body = _get(
        app,
        f"/v1/projects/tenant-a/coverage/stories/{story.story_display_id}/are-evidence",
    )
    assert status == HTTPStatus.OK
    evidence = body["story_are_evidence"]  # type: ignore[index]
    reqs = {r["are_item_id"]: r for r in evidence["linked_requirements"]}
    # ARE-300 is NOT in uncovered -> covered; has one evidence_path
    assert reqs["ARE-300"]["coverage_status"] == "covered"
    assert reqs["ARE-300"]["evidence_paths"] == ["tests/unit/test_foo.py::test_bar"], (
        "evidence_paths must be populated from AreClient.list_evidence (ERROR 3)"
    )
    # ARE-400 IS in uncovered -> uncovered; no evidence submitted
    assert reqs["ARE-400"]["coverage_status"] == "uncovered"
    assert reqs["ARE-400"]["evidence_paths"] == [], (
        "ARE-400 has no submitted evidence — evidence_paths must be empty list"
    )


# ---------------------------------------------------------------------------
# R5 MAJOR 2: flow E2E proof persists REAL payload fields (not unit-only)
#
# These tests write a real PhaseState WITH the round-3 defect-surface payload
# fields (ImplementationPayload.qa_cycle_round, ClosurePayload.progress, and
# ExplorationPayload.gate_status) through the canonical save_phase_state write
# path, then GET /flow over the REAL ReadModelRoutes + REAL backend + REAL DB,
# and assert the derivation reflects the real persisted payload (AC10). No mock
# at the backend/DB boundary.
# ---------------------------------------------------------------------------


def _app_with_real_phase_state(
    tmp_path: Path,
    phase_state: object,
) -> ControlPlaneApplication:
    """Persist a real PhaseState and wire the app to read it from the same DB.

    Uses ``save_phase_state`` (canonical write path) plus a ``phase_state_loader``
    that targets the SAME tmp_path-scoped SQLite store via the real
    ``load_phase_state_global`` — no stub at the backend/DB boundary.
    """
    from agentkit.backend.pipeline_engine.phase_executor import PhaseState
    from agentkit.backend.state_backend.pipeline_runtime_store import (
        load_phase_state_global,
        save_phase_state,
    )

    assert isinstance(phase_state, PhaseState)
    save_phase_state(tmp_path, phase_state)

    def _phase_loader(sid: str) -> object:
        return load_phase_state_global(sid, tmp_path)

    project_repo = StateBackendProjectRepository(tmp_path)
    story_svc = _story_service(tmp_path)
    config_repo = StateBackendParallelizationConfigRepository(tmp_path)
    are_repo = StateBackendStoryAreLinkRepository(tmp_path)
    detail_service = ProjectDetailService(
        project_repository=project_repo,
        story_service=story_svc,
    )
    tenant_scope = TenantScopeMiddleware(repository=project_repo)
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=ProjectManagementRoutes(
                repository=project_repo,
                repos_in_use_checker=_no_repos_in_use,
                detail_service=detail_service,
            ),
            read_model_routes=ReadModelRoutes(
                project_repository=project_repo,
                story_service=story_svc,
                config_repository=config_repo,
                are_link_repository=are_repo,
                phase_state_loader=_phase_loader,
            ),
        ),
        tenant_scope_middleware=tenant_scope,
    )


def _start_story(tmp_path: Path, *, op_suffix: str) -> Story:
    """Create + approve + begin_progress a story (In Progress for flow derivation)."""
    svc = _story_service(tmp_path)
    story = svc.create_story(
        CreateStoryInput(
            project_key="tenant-a",
            title=f"Payload flow {op_suffix}",
            type="implementation",
            repos=["repo-a"],
        ),
        op_id=f"op-create-{op_suffix}",
    )
    svc.approve_story(story.story_display_id, op_id=f"op-approve-{op_suffix}")
    svc.begin_progress(story.story_display_id)
    return story

def test_flow_implementation_payload_qa_cycle_round_through_real_db(
    tmp_path: Path,
) -> None:
    """MAJOR 2: real ImplementationPayload.qa_cycle_round drives flow iteration via DB.

    Persists a real PhaseState (implementation / IN_PROGRESS) whose payload is a
    real ImplementationPayload(qa_cycle_round=N), then GET /flow and asserts the
    implementation phase's loop ``iteration`` reflects the real N — proven through
    the real HTTP -> DB -> read-model path, not a builder unit test.
    """
    from tests.phase_state_factory import make_phase_state

    from agentkit.backend.pipeline_engine.phase_executor.models import (
        ImplementationPayload,
        PhaseStatus,
        QaCycleStatus,
    )

    _seed_project(tmp_path)
    story = _start_story(tmp_path, op_suffix="impl")

    real_round = 3
    phase_state = make_phase_state(
        story_id=story.story_display_id,
        phase="implementation",
        status=PhaseStatus.IN_PROGRESS,
        payload=ImplementationPayload(
            qa_cycle_round=real_round,
            qa_cycle_status=QaCycleStatus.AWAITING_REMEDIATION,
        ),
    )
    app = _app_with_real_phase_state(tmp_path, phase_state)

    status, body = _get(
        app,
        f"/v1/projects/tenant-a/stories/{story.story_display_id}/flow",
    )
    assert status == HTTPStatus.OK
    snapshot = body["story_flow_snapshot"]  # type: ignore[index]
    phases = {p["phase"]: p for p in snapshot["phases"]}
    # Implementation phase is active and surfaces the REAL persisted qa_cycle_round.
    assert phases["implementation"]["state"] == "active"
    assert phases["implementation"]["iteration"] == real_round, (
        "implementation iteration must reflect the REAL persisted "
        f"ImplementationPayload.qa_cycle_round={real_round} via the DB read path, "
        f"got {phases['implementation'].get('iteration')!r}"
    )
    assert phases["implementation"]["iteration_loop_group"] == "remediation"
    # Position-based derivation: earlier phases done, later pending.
    assert phases["setup"]["state"] == "done"
    assert phases["exploration"]["state"] == "done"
    assert phases["closure"]["state"] == "pending"


def test_flow_closure_payload_progress_through_real_db(tmp_path: Path) -> None:
    """MAJOR 2: real ClosurePayload.progress checkpoints drive substep states via DB.

    Persists a real PhaseState (closure / IN_PROGRESS) whose payload is a real
    ClosurePayload(progress=ClosureProgress(...)) with some checkpoints True,
    then GET /flow and asserts the closure substep states reflect the real
    ClosureProgress checkpoints through the real DB read path.
    """
    from tests.phase_state_factory import make_phase_state

    from agentkit.backend.pipeline_engine.phase_executor.models import (
        ClosurePayload,
        ClosureProgress,
        PhaseStatus,
    )

    _seed_project(tmp_path)
    story = _start_story(tmp_path, op_suffix="closure")

    # Ordered checkpoints: integrity -> branch_push -> merge are done.
    progress = ClosureProgress(
        integrity_passed=True,
        story_branch_pushed=True,
        merge_done=True,
    )
    phase_state = make_phase_state(
        story_id=story.story_display_id,
        phase="closure",
        status=PhaseStatus.IN_PROGRESS,
        payload=ClosurePayload(progress=progress),
    )
    app = _app_with_real_phase_state(tmp_path, phase_state)

    status, body = _get(
        app,
        f"/v1/projects/tenant-a/stories/{story.story_display_id}/flow",
    )
    assert status == HTTPStatus.OK
    snapshot = body["story_flow_snapshot"]  # type: ignore[index]
    phases = {p["phase"]: p for p in snapshot["phases"]}
    closure = phases["closure"]
    assert closure["state"] == "active"
    sub_state = {s["substep"]: s["state"] for s in closure["substeps"]}
    # Done checkpoints -> done substeps (real ClosureProgress -> derivation).
    assert sub_state["integrity_gate"] == "done", (
        "integrity_gate substep must be 'done' for real "
        "ClosureProgress.integrity_passed=True via DB read path"
    )
    assert sub_state["branch_push"] == "done"
    assert sub_state["merge"] == "done"
    # Checkpoints not yet reached -> still pending.
    assert sub_state["story_close"] == "pending"
    assert sub_state["metrics"] == "pending"
    assert sub_state["postflight"] == "pending"
    # Prior phases done, no later phase after closure.
    assert phases["setup"]["state"] == "done"
    assert phases["implementation"]["state"] == "done"


def test_flow_exploration_payload_gate_status_through_real_db(tmp_path: Path) -> None:
    """MAJOR 2: real ExplorationPayload.gate_status drives substep states via DB.

    Persists a real PhaseState (exploration / IN_PROGRESS) whose payload is a
    real ExplorationPayload(gate_status=APPROVED), then GET /flow and asserts the
    exploration substeps reflect the real gate_status (all done) through the real
    DB read path.
    """
    from tests.phase_state_factory import make_phase_state

    from agentkit.backend.core_types import ExplorationGateStatus
    from agentkit.backend.pipeline_engine.phase_executor.models import (
        ExplorationPayload,
        PhaseStatus,
    )

    _seed_project(tmp_path)
    story = _start_story(tmp_path, op_suffix="explore")

    phase_state = make_phase_state(
        story_id=story.story_display_id,
        phase="exploration",
        status=PhaseStatus.IN_PROGRESS,
        payload=ExplorationPayload(gate_status=ExplorationGateStatus.APPROVED),
    )
    app = _app_with_real_phase_state(tmp_path, phase_state)

    status, body = _get(
        app,
        f"/v1/projects/tenant-a/stories/{story.story_display_id}/flow",
    )
    assert status == HTTPStatus.OK
    snapshot = body["story_flow_snapshot"]  # type: ignore[index]
    phases = {p["phase"]: p for p in snapshot["phases"]}
    exploration = phases["exploration"]
    assert exploration["state"] == "active"
    # gate_status=approved -> non-optional substeps all 'done' (real derivation).
    non_optional = [
        s for s in exploration["substeps"] if not s["optional"]
    ]
    assert non_optional, "exploration must have non-optional substeps in standard mode"
    assert all(s["state"] == "done" for s in non_optional), (
        "exploration substeps must be 'done' for real "
        "ExplorationPayload.gate_status=APPROVED via DB read path; got "
        f"{[(s['substep'], s['state']) for s in non_optional]}"
    )
    # setup done (before), implementation/closure pending (after).
    assert phases["setup"]["state"] == "done"
    assert phases["implementation"]["state"] == "pending"
    assert phases["closure"]["state"] == "pending"
