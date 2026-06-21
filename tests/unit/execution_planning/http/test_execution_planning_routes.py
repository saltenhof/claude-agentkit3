from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus

from agentkit.backend.control_plane.http import ControlPlaneApplication
from agentkit.backend.control_plane_http.app import ControlPlaneApplicationRoutes
from agentkit.backend.execution_planning.entities import (
    ParallelizationConfig,
    StoryDependency,
    StoryDependencyKind,
    StoryRefForPlanning,
)
from agentkit.backend.execution_planning.errors import (
    StoryDependencyConflictError,
    StoryDependencyNotFoundError,
)
from agentkit.backend.execution_planning.http.routes import ExecutionPlanningRoutes
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.project_management.lifecycle import archive_project, create_project


@dataclass
class _ProjectRepo:
    archived: bool = False

    def get(self, key: str) -> Project | None:
        if key != "tenant-a":
            return None
        project = create_project(
            "tenant-a",
            "Tenant A",
            "AK3",
            ProjectConfiguration(
                repo_url="",
                default_branch="main",
                are_url=None,
                default_worker_count=1,
                repositories=["https://example.test/repo.git"],
            ),
            repositories=["https://example.test/repo.git"],
        )
        if self.archived:
            return archive_project(project, archived_at=datetime.now(UTC))
        return project

    def list(self, *, include_archived: bool = False) -> list[Project]:
        del include_archived
        project = self.get("tenant-a")
        return [project] if project is not None else []

    def save(self, project: Project) -> None:
        del project


@dataclass
class _StoryRepo:
    stories: dict[str, StoryRefForPlanning]

    def get(self, project_key: str, story_id: str) -> StoryRefForPlanning | None:
        del project_key
        return self.stories.get(story_id)

    def list_for_project(self, project_key: str) -> list[StoryRefForPlanning]:
        del project_key
        return list(self.stories.values())


@dataclass
class _DepRepo:
    edges: list[StoryDependency] = field(default_factory=list)

    def list_for_project(self, project_key: str) -> list[StoryDependency]:
        del project_key
        return list(self.edges)

    def list_for_story(self, story_id: str) -> list[StoryDependency]:
        return [edge for edge in self.edges if edge.story_id == story_id]

    def add(self, edge: StoryDependency, *, project_key: str) -> None:
        del project_key
        if edge in self.edges:
            raise StoryDependencyConflictError("duplicate")
        self.edges.append(edge)

    def remove(
        self,
        story_id: str,
        depends_on_story_id: str,
        kind: StoryDependencyKind,
    ) -> None:
        before = len(self.edges)
        self.edges = [
            edge
            for edge in self.edges
            if not (
                edge.story_id == story_id
                and edge.depends_on_story_id == depends_on_story_id
                and edge.kind == kind
            )
        ]
        if len(self.edges) == before:
            raise StoryDependencyNotFoundError("missing")


@dataclass
class _ConfigRepo:
    config: ParallelizationConfig | None = None

    def get(self, project_key: str) -> ParallelizationConfig | None:
        del project_key
        return self.config

    def upsert(self, config: ParallelizationConfig) -> None:
        self.config = config


def _story(number: int, *, status: str = "defined") -> StoryRefForPlanning:
    return StoryRefForPlanning(
        project_key="tenant-a",
        story_id=f"AK3-{number:03d}",
        story_number=number,
        title=f"Story {number}",
        lifecycle_status=status,
    )


def test_routes_default_dependency_repo_is_planning_write_path() -> None:
    """AG3-099: the default-wired dependency repository is the planning-write-path one.

    With ``dependency_repository=None`` the route handler must construct the
    BC-9 planning-write-path repository (no legacy direct ``story_dependencies``
    write), so HTTP edge writes share the planning projection source of truth
    (FK-70 §70.10.2). Construction is side-effect-free (no DB connect), so the
    other repos are injected to isolate the dependency-wiring branch.
    """
    from agentkit.backend.state_backend.store.planning_story_dependency_repository import (
        PlanningWritePathStoryDependencyRepository,
    )

    routes = ExecutionPlanningRoutes(
        project_repository=_ProjectRepo(),
        story_repository=_StoryRepo({}),
        dependency_repository=None,  # force the default-wiring branch
        config_repository=_ConfigRepo(),
    )
    assert isinstance(
        routes._dependency_repository,  # noqa: SLF001
        PlanningWritePathStoryDependencyRepository,
    )


class _NoopTenantScopeMiddleware:
    """Passthrough stub: all project-scoped paths pass without DB access (AG3-090)."""

    def validate(self, *, method: str, route_path: str, correlation_id: str) -> None:
        return None


def _app(
    *,
    dep_repo: _DepRepo | None = None,
    config_repo: _ConfigRepo | None = None,
    project_repo: _ProjectRepo | None = None,
) -> ControlPlaneApplication:
    stories = {
        "AK3-001": _story(1, status="done"),
        "AK3-002": _story(2),
        "AK3-003": _story(3),
    }
    routes = ExecutionPlanningRoutes(
        project_repository=project_repo or _ProjectRepo(),
        story_repository=_StoryRepo(stories),
        dependency_repository=dep_repo or _DepRepo(),
        config_repository=config_repo or _ConfigRepo(),
    )
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(planning_routes=routes),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )


def _json(body: bytes) -> dict[str, object]:
    result = json.loads(body.decode("utf-8"))
    assert isinstance(result, dict)
    return result


def test_get_dependency_graph() -> None:
    response = _app().handle_request(
        method="GET",
        path="/v1/projects/tenant-a/planning/dependency-graph",
        body=b"",
    )

    assert response.status_code == HTTPStatus.OK
    assert _json(response.body)["dependencies"] == []


def test_post_dependency_and_next_ready() -> None:
    dep_repo = _DepRepo()
    app = _app(dep_repo=dep_repo)

    post = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/planning/dependencies",
        body=json.dumps(
            {
                "story_id": "AK3-003",
                "depends_on_story_id": "AK3-002",
                "kind": "hard_story_dependency",
                "op_id": "op-test",
            },
        ).encode("utf-8"),
        request_headers={"X-Correlation-Id": "corr-test"},
    )
    ready = app.handle_request(
        method="GET",
        path="/v1/projects/tenant-a/planning/next-ready",
        body=b"",
    )

    assert post.status_code == HTTPStatus.CREATED
    assert _json(post.body)["correlation_id"] == "corr-test"
    ready_body = _json(ready.body)
    next_ready_raw = ready_body["next_ready"]
    assert isinstance(next_ready_raw, list)
    next_ready: list[dict[str, object]] = [s for s in next_ready_raw if isinstance(s, dict)]
    assert [s["story_id"] for s in next_ready] == ["AK3-002"]


def test_delete_dependency() -> None:
    edge = StoryDependency(
        story_id="AK3-003",
        depends_on_story_id="AK3-002",
        kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
        created_at=datetime.now(UTC),
    )
    dep_repo = _DepRepo([edge])
    response = _app(dep_repo=dep_repo).handle_request(
        method="DELETE",
        path="/v1/projects/tenant-a/planning/dependencies/AK3-003/AK3-002/hard_story_dependency",
        body=b"",
    )

    assert response.status_code == HTTPStatus.OK
    assert dep_repo.edges == []


def test_config_get_and_put() -> None:
    config_repo = _ConfigRepo()
    app = _app(config_repo=config_repo)

    get_default = app.handle_request(
        method="GET",
        path="/v1/projects/tenant-a/planning/config",
        body=b"",
    )
    put = app.handle_request(
        method="PUT",
        path="/v1/projects/tenant-a/planning/config",
        body=json.dumps({"max_parallel_stories": 2, "op_id": "op-config"}).encode(
            "utf-8",
        ),
    )

    default_config = _json(get_default.body)["config"]
    assert isinstance(default_config, dict) and default_config["max_parallel_stories"] == 1
    assert put.status_code == HTTPStatus.OK
    assert config_repo.config == ParallelizationConfig(
        project_key="tenant-a",
        max_parallel_stories=2,
    )


def test_conflicts_and_not_found_status_codes() -> None:
    archived = _app(project_repo=_ProjectRepo(archived=True)).handle_request(
        method="POST",
        path="/v1/projects/tenant-a/planning/dependencies",
        body=json.dumps(
            {
                "story_id": "AK3-002",
                "depends_on_story_id": "AK3-001",
                "kind": "hard_story_dependency",
            },
        ).encode("utf-8"),
    )
    missing = _app().handle_request(
        method="GET",
        path="/v1/projects/missing/planning/config",
        body=b"",
    )

    assert archived.status_code == HTTPStatus.CONFLICT
    assert missing.status_code == HTTPStatus.NOT_FOUND
