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
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    IdempotencyRequest,
    InMemoryInflightIdempotencyGuard,
    compute_body_hash,
)


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
    guard: InMemoryInflightIdempotencyGuard | None = None,
) -> ControlPlaneApplication:
    stories = {
        "AK3-001": _story(1, status="done"),
        "AK3-002": _story(2),
        "AK3-003": _story(3),
    }
    # AG3-140: the mutating routes now run the unified idempotency contract; unit
    # tests inject the first-class in-memory guard (the production default is the
    # Postgres-backed guard, unavailable here). One guard per app -> shared across
    # the requests issued on that app, so replay/mismatch/in-flight are exercised.
    routes = ExecutionPlanningRoutes(
        project_repository=project_repo or _ProjectRepo(),
        story_repository=_StoryRepo(stories),
        dependency_repository=dep_repo or _DepRepo(),
        config_repository=config_repo or _ConfigRepo(),
        idempotency_guard=guard or InMemoryInflightIdempotencyGuard(),
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
        body=json.dumps({"op_id": "op-del"}).encode("utf-8"),
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
                "op_id": "op-dependency-archived-001",
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


# ---------------------------------------------------------------------------
# AG3-140: the unified idempotency contract on the mutating planning routes
# ---------------------------------------------------------------------------

_DEP_PATH = "/v1/projects/tenant-a/planning/dependencies"
_DETAIL = _DEP_PATH + "/AK3-003/AK3-002/hard_story_dependency"


def _create_body(op_id: str, *, depends_on: str = "AK3-002") -> bytes:
    return json.dumps(
        {
            "story_id": "AK3-003",
            "depends_on_story_id": depends_on,
            "kind": "hard_story_dependency",
            "op_id": op_id,
        }
    ).encode("utf-8")


def _existing_edge() -> StoryDependency:
    return StoryDependency(
        story_id="AK3-003",
        depends_on_story_id="AK3-002",
        kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
        created_at=datetime.now(UTC),
    )


def test_delete_dependency_missing_op_id_returns_422() -> None:
    app = _app(dep_repo=_DepRepo([_existing_edge()]))
    resp = app.handle_request(method="DELETE", path=_DETAIL, body=b"{}")
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _json(resp.body)["error_code"] == "invalid_dependency_delete_payload"


def test_delete_dependency_replay_returns_stored_result_without_second_remove() -> None:
    dep_repo = _DepRepo([_existing_edge()])
    app = _app(dep_repo=dep_repo)
    body = json.dumps({"op_id": "op-del-replay"}).encode("utf-8")
    first = app.handle_request(method="DELETE", path=_DETAIL, body=body)
    second = app.handle_request(method="DELETE", path=_DETAIL, body=body)
    assert first.status_code == HTTPStatus.OK
    # A second real remove would raise StoryDependencyNotFoundError -> 404; the
    # replay returns the stored 200 instead (remove ran exactly once).
    assert second.status_code == HTTPStatus.OK
    assert first.body == second.body
    assert dep_repo.edges == []


def test_delete_dependency_same_op_id_different_target_returns_409_mismatch() -> None:
    dep_repo = _DepRepo(
        [
            _existing_edge(),
            StoryDependency(
                story_id="AK3-003",
                depends_on_story_id="AK3-001",
                kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
                created_at=datetime.now(UTC),
            ),
        ]
    )
    app = _app(dep_repo=dep_repo)
    body = json.dumps({"op_id": "op-del-x"}).encode("utf-8")
    first = app.handle_request(method="DELETE", path=_DETAIL, body=body)
    # SAME op_id, DIFFERENT target dependency (depends_on AK3-001) -> 409 mismatch.
    other = "/v1/projects/tenant-a/planning/dependencies/AK3-003/AK3-001/hard_story_dependency"
    second = app.handle_request(method="DELETE", path=other, body=body)
    assert first.status_code == HTTPStatus.OK
    assert second.status_code == HTTPStatus.CONFLICT
    assert _json(second.body)["error_code"] == "idempotency_mismatch"


def test_delete_dependency_in_flight_returns_409() -> None:
    guard = InMemoryInflightIdempotencyGuard()
    guard.claim(
        IdempotencyRequest(
            op_id="op-del-inflight",
            operation_kind="story_dependency_remove",
            body_hash=compute_body_hash({"any": "claim"}),
            project_key="tenant-a",
        )
    )
    app = _app(dep_repo=_DepRepo([_existing_edge()]), guard=guard)
    resp = app.handle_request(
        method="DELETE",
        path=_DETAIL,
        body=json.dumps({"op_id": "op-del-inflight"}).encode("utf-8"),
    )
    assert resp.status_code == HTTPStatus.CONFLICT
    assert _json(resp.body)["error_code"] == "operation_in_flight"


def test_delete_dependency_replay_after_not_found_returns_stored_404() -> None:
    # No edge present -> first delete is a deterministic 404; the replay returns
    # the SAME stored 404 (AC8 replay-after-failure).
    app = _app(dep_repo=_DepRepo([]))
    body = json.dumps({"op_id": "op-del-404"}).encode("utf-8")
    first = app.handle_request(method="DELETE", path=_DETAIL, body=body)
    second = app.handle_request(method="DELETE", path=_DETAIL, body=body)
    assert first.status_code == HTTPStatus.NOT_FOUND
    assert second.status_code == HTTPStatus.NOT_FOUND
    assert first.body == second.body


def test_create_dependency_replay_returns_stored_result() -> None:
    dep_repo = _DepRepo()
    app = _app(dep_repo=dep_repo)
    first = app.handle_request(method="POST", path=_DEP_PATH, body=_create_body("op-c"))
    second = app.handle_request(method="POST", path=_DEP_PATH, body=_create_body("op-c"))
    assert first.status_code == HTTPStatus.CREATED
    # A second real add of the same edge would 409 (conflict); the replay returns
    # the stored 201 and add ran once.
    assert second.status_code == HTTPStatus.CREATED
    assert first.body == second.body
    assert len(dep_repo.edges) == 1


def test_create_dependency_same_op_id_different_body_returns_409_mismatch() -> None:
    app = _app(dep_repo=_DepRepo())
    first = app.handle_request(method="POST", path=_DEP_PATH, body=_create_body("op-c2"))
    second = app.handle_request(
        method="POST", path=_DEP_PATH, body=_create_body("op-c2", depends_on="AK3-001")
    )
    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CONFLICT
    assert _json(second.body)["error_code"] == "idempotency_mismatch"


def test_create_dependency_in_flight_returns_409() -> None:
    guard = InMemoryInflightIdempotencyGuard()
    guard.claim(
        IdempotencyRequest(
            op_id="op-c-inflight",
            operation_kind="story_dependency_add",
            body_hash=compute_body_hash({"any": "claim"}),
            project_key="tenant-a",
        )
    )
    app = _app(dep_repo=_DepRepo(), guard=guard)
    resp = app.handle_request(method="POST", path=_DEP_PATH, body=_create_body("op-c-inflight"))
    assert resp.status_code == HTTPStatus.CONFLICT
    assert _json(resp.body)["error_code"] == "operation_in_flight"


def test_put_config_replay_returns_stored_result() -> None:
    config_repo = _ConfigRepo()
    app = _app(config_repo=config_repo)
    body = json.dumps({"max_parallel_stories": 3, "op_id": "op-cfg"}).encode("utf-8")
    first = app.handle_request(method="PUT", path=_CFG_PATH, body=body)
    second = app.handle_request(method="PUT", path=_CFG_PATH, body=body)
    assert first.status_code == HTTPStatus.OK
    assert second.status_code == HTTPStatus.OK
    assert first.body == second.body


def test_put_config_same_op_id_different_body_returns_409_mismatch() -> None:
    app = _app(config_repo=_ConfigRepo())
    first = app.handle_request(
        method="PUT",
        path=_CFG_PATH,
        body=json.dumps({"max_parallel_stories": 3, "op_id": "op-cfg2"}).encode("utf-8"),
    )
    second = app.handle_request(
        method="PUT",
        path=_CFG_PATH,
        body=json.dumps({"max_parallel_stories": 5, "op_id": "op-cfg2"}).encode("utf-8"),
    )
    assert first.status_code == HTTPStatus.OK
    assert second.status_code == HTTPStatus.CONFLICT
    assert _json(second.body)["error_code"] == "idempotency_mismatch"


_CFG_PATH = "/v1/projects/tenant-a/planning/config"
