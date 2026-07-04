from __future__ import annotations

import json
from http import HTTPStatus
from unittest.mock import patch

from agentkit.backend.control_plane.http import ControlPlaneApplication
from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplicationRoutes,
    HttpResponse,
)
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.project_management.http.routes import (
    ProjectManagementRoutes,
    _no_repos_in_use,
)
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    IdempotencyRequest,
    InMemoryInflightIdempotencyGuard,
)


class _InMemoryProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[str, Project] = {}

    def get(self, key: str) -> Project | None:
        return self.projects.get(key)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        projects = sorted(self.projects.values(), key=lambda project: project.key)
        if include_archived:
            return projects
        return [project for project in projects if project.archived_at is None]

    def save(self, project: Project) -> None:
        for existing in self.projects.values():
            if (
                existing.key != project.key
                and existing.story_id_prefix == project.story_id_prefix
            ):
                from agentkit.backend.project_management.errors import (
                    ProjectStoryIdPrefixConflictError,
                )

                raise ProjectStoryIdPrefixConflictError(
                    "Story-id prefix already belongs to another project",
                )
        self.projects[project.key] = project


class _StoryListStub:
    """Minimal story-listing port returning a fixed story corpus."""

    def __init__(self, stories: list[object] | None = None) -> None:
        self._stories = stories or []

    def list_stories_with_dependencies(self, project_key: str) -> list[object]:
        _ = project_key
        return list(self._stories)


class _NoopTenantScopeMiddleware:
    """Passthrough stub: all project-scoped paths pass without DB access (AG3-090)."""

    def validate(self, *, method: str, route_path: str, correlation_id: str) -> None:
        return None


def _app(
    repository: _InMemoryProjectRepository,
    *,
    stories: list[object] | None = None,
) -> ControlPlaneApplication:
    from agentkit.backend.project_management.service import ProjectDetailService

    detail_service = ProjectDetailService(
        project_repository=repository,
        story_service=_StoryListStub(stories),
    )
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=ProjectManagementRoutes(
                repository=repository,
                repos_in_use_checker=_no_repos_in_use,
                detail_service=detail_service,
                # AG3-140: a first-class in-memory idempotency guard (NOT a mock)
                # so mutating routes exercise the real claim->finalize contract
                # without a database.  Single-call tests get a fresh guard.
                idempotency_guard=InMemoryInflightIdempotencyGuard(),
            ),
        ),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )


def _app_with_guard(
    repository: _InMemoryProjectRepository,
    guard: InMemoryInflightIdempotencyGuard,
) -> ControlPlaneApplication:
    """Build a project-management app with a SHARED idempotency guard injected.

    The same ``guard`` instance persists claim state across calls within one
    test, so replay / mismatch / in-flight can be driven end-to-end.
    """
    routes = ProjectManagementRoutes(
        repository=repository,
        repos_in_use_checker=_no_repos_in_use,
        idempotency_guard=guard,
    )
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(project_routes=routes),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )


def _configuration_payload() -> dict[str, object]:
    # ``repo_url=""`` opts out of the AG3-020 consistency check (the field is
    # only enforced when a primary URL is set).  These fixture-driven tests
    # focus on the repositories-update path, not on the primary-URL contract.
    return {
        "repo_url": "",
        "default_branch": "main",
        "are_url": None,
        "default_worker_count": 2,
        "repositories": ["https://example.test/repo.git"],
    }


def _project() -> Project:
    return Project(
        key="tenant-a",
        name="Tenant A",
        story_id_prefix="AG3",
        configuration=ProjectConfiguration.model_validate(_configuration_payload()),
        archived_at=None,
    )


def _json_body(response_body: bytes) -> dict[str, object]:
    body = json.loads(response_body.decode("utf-8"))
    assert isinstance(body, dict)
    return body


def test_get_projects_returns_list() -> None:
    repository = _InMemoryProjectRepository()
    repository.save(_project())

    response = _app(repository).handle_request(
        method="GET",
        path="/v1/projects",
        body=b"",
        request_headers={"X-Correlation-Id": "req-projects"},
    )

    assert response.status_code == HTTPStatus.OK
    # GET /v1/projects returns the project_summary wire shape (exactly the
    # three canonical fields), NOT the raw entity (AG3-040 sub-block a).
    assert _json_body(response.body)["projects"] == [
        {
            "project_key": "tenant-a",
            "display_name": "Tenant A",
            "status": "active",
        },
    ]
    assert ("X-Correlation-Id", "req-projects") in response.headers


def test_get_project_returns_detail() -> None:
    repository = _InMemoryProjectRepository()
    repository.save(_project())

    response = _app(repository).handle_request(
        method="GET",
        path="/v1/projects/tenant-a",
        body=b"",
        request_headers={"X-Correlation-Id": "req-project"},
    )

    assert response.status_code == HTTPStatus.OK
    project_payload = _json_body(response.body)["project"]
    assert isinstance(project_payload, dict)
    # GET /v1/projects/{key} returns the flat project_detail wire view.
    assert project_payload == {
        "project_key": "tenant-a",
        "display_name": "Tenant A",
        "status": "active",
        "mode_lock": {"project_key": "tenant-a", "mode": "idle"},
        "story_counters": {
            "project_key": "tenant-a",
            "total": 0,
            "finished": 0,
            "running": 0,
            "ready": 0,
            "queue": 0,
            "blocked": 0,
        },
        "concept_anchors": [],
    }


def test_post_projects_creates_project() -> None:
    repository = _InMemoryProjectRepository()
    payload = {
        "key": "tenant-a",
        "name": "Tenant A",
        "story_id_prefix": "AG3",
        "configuration": _configuration_payload(),
        "op_id": "op-create-project",
    }

    response = _app(repository).handle_request(
        method="POST",
        path="/v1/projects",
        body=json.dumps(payload).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-create"},
    )

    body = _json_body(response.body)
    assert response.status_code == HTTPStatus.CREATED
    assert body["op_id"] == "op-create-project"
    assert body["correlation_id"] == "req-create"
    assert repository.get("tenant-a") is not None


def test_patch_project_updates_configuration() -> None:
    repository = _InMemoryProjectRepository()
    repository.save(_project())

    response = _app(repository).handle_request(
        method="PATCH",
        path="/v1/projects/tenant-a",
        body=json.dumps(
            {
                "name": "Tenant Alpha",
                "configuration": {"default_worker_count": 4},
                "op_id": "op-update-project",
            },
        ).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-update"},
    )

    updated = repository.get("tenant-a")
    assert response.status_code == HTTPStatus.OK
    assert updated is not None
    assert updated.name == "Tenant Alpha"
    assert updated.configuration.default_worker_count == 4


def test_patch_project_rejects_immutable_fields() -> None:
    repository = _InMemoryProjectRepository()
    repository.save(_project())

    response = _app(repository).handle_request(
        method="PATCH",
        path="/v1/projects/tenant-a",
        body=json.dumps(
            {"story_id_prefix": "OTHER", "op_id": "op-patch-immutable-001"}
        ).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-update"},
    )

    assert response.status_code == HTTPStatus.CONFLICT


def test_post_project_archive_archives_project() -> None:
    repository = _InMemoryProjectRepository()
    repository.save(_project())

    response = _app(repository).handle_request(
        method="POST",
        path="/v1/projects/tenant-a/archive",
        body=json.dumps({"op_id": "op-archive-project"}).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-archive"},
    )

    archived = repository.get("tenant-a")
    assert response.status_code == HTTPStatus.OK
    assert archived is not None
    assert archived.archived_at is not None


def test_get_missing_project_returns_404() -> None:
    response = _app(_InMemoryProjectRepository()).handle_request(
        method="GET",
        path="/v1/projects/missing",
        body=b"",
        request_headers={"X-Correlation-Id": "req-missing"},
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_post_duplicate_project_returns_409() -> None:
    repository = _InMemoryProjectRepository()
    repository.save(_project())
    payload = {
        "key": "tenant-a",
        "name": "Tenant A",
        "story_id_prefix": "AG3",
        "configuration": _configuration_payload(),
        "op_id": "op-duplicate-project-001",
    }

    response = _app(repository).handle_request(
        method="POST",
        path="/v1/projects",
        body=json.dumps(payload).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-conflict"},
    )

    assert response.status_code == HTTPStatus.CONFLICT


# ---------------------------------------------------------------------------
# AG3-020: repositories field HTTP-level tests
# ---------------------------------------------------------------------------


def test_post_project_without_repositories_returns_400_validation_failed() -> None:
    """AG3-020 AC3: POST /v1/projects without repositories MUST return 400 validation_failed.

    Replaces the earlier permissive ``backfill``-test that hid the missing
    field behind a model-validator default.  The strict schema (finding 1
    fix from the second review) requires ``repositories`` explicitly.
    """
    repository = _InMemoryProjectRepository()
    config_without_repos = {
        "repo_url": "https://example.test/repo.git",
        "default_branch": "main",
        "are_url": None,
        "default_worker_count": 2,
        # repositories absent — strict schema must reject this
    }
    payload = {
        "key": "tenant-b",
        "name": "Tenant B",
        "story_id_prefix": "TB",
        "configuration": config_without_repos,
        "op_id": "op-create-without-repos",
    }

    response = _app(repository).handle_request(
        method="POST",
        path="/v1/projects",
        body=json.dumps(payload).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-create-no-repos"},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    body = _json_body(response.body)
    assert body["error_code"] == "validation_failed"
    assert "invalid_repos" in str(body.get("detail", ""))
    assert repository.get("tenant-b") is None


def test_post_project_with_empty_repositories_returns_400_validation_failed() -> None:
    """AG3-020 AC3: POST /v1/projects with repositories=[] returns 400 validation_failed."""
    repository = _InMemoryProjectRepository()
    payload = {
        "key": "tenant-c",
        "name": "Tenant C",
        "story_id_prefix": "TC",
        "configuration": {
            "repo_url": "https://example.test/repo.git",
            "default_branch": "main",
            "are_url": None,
            "default_worker_count": 1,
            "repositories": [],
        },
        "op_id": "op-create-empty-repos",
    }

    response = _app(repository).handle_request(
        method="POST",
        path="/v1/projects",
        body=json.dumps(payload).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-create-empty-repos"},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    body = _json_body(response.body)
    assert body["error_code"] == "validation_failed"
    assert "invalid_repos" in str(body.get("detail", ""))
    assert repository.get("tenant-c") is None


def test_post_project_with_repositories_persists_list() -> None:
    """POST /v1/projects with explicit repositories stores the list.

    ``repo_url`` is the primary-URL contract (AG3-020 §2.1.1); when set, it
    must be a member of ``repositories``.  Here the primary URL is the same
    as the first repository entry.
    """
    repository = _InMemoryProjectRepository()
    payload = {
        "key": "tenant-c",
        "name": "Tenant C",
        "story_id_prefix": "TC",
        "configuration": {
            "repo_url": "primary-repo",
            "default_branch": "main",
            "are_url": None,
            "default_worker_count": 1,
            "repositories": ["primary-repo", "secondary-repo"],
        },
        "op_id": "op-create-with-repos",
    }

    response = _app(repository).handle_request(
        method="POST",
        path="/v1/projects",
        body=json.dumps(payload).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-create-repos"},
    )

    assert response.status_code == HTTPStatus.CREATED
    project = repository.get("tenant-c")
    assert project is not None
    assert project.configuration.repositories == ["primary-repo", "secondary-repo"]


def test_patch_configuration_updates_repositories() -> None:
    """PATCH /v1/projects/{key}/configuration with repositories replaces the list."""
    repository = _InMemoryProjectRepository()
    repository.save(_project())

    response = _app(repository).handle_request(
        method="PATCH",
        path="/v1/projects/tenant-a/configuration",
        body=json.dumps(
            {"repositories": ["repo-a", "repo-b"], "op_id": "op-patch-config-001"}
        ).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-patch-config"},
    )

    assert response.status_code == HTTPStatus.OK
    project = repository.get("tenant-a")
    assert project is not None
    assert project.configuration.repositories == ["repo-a", "repo-b"]


def test_patch_configuration_repos_in_use_returns_validation_failed() -> None:
    """PATCH /v1/projects/{key}/configuration that removes a repo still in use returns 400."""
    repository = _InMemoryProjectRepository()
    repository.save(_project())

    def _checker(project_key: str, repos: list[str]) -> list[str]:
        # Simulate: "repo-in-use" is still referenced by an active story.
        return [r for r in repos if r == "https://example.test/repo.git"]

    routes = ProjectManagementRoutes(
        repository=repository,
        repos_in_use_checker=_checker,
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
    )
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(project_routes=routes),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="PATCH",
        path="/v1/projects/tenant-a/configuration",
        body=json.dumps(
            {"repositories": ["new-repo"], "op_id": "op-patch-repos-in-use-001"}
        ).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-patch-repos-in-use"},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    body = _json_body(response.body)
    assert body["error_code"] == "validation_failed"
    assert "repos_still_in_use" in str(body.get("detail", ""))


def test_patch_configuration_repos_not_in_use_succeeds() -> None:
    """PATCH /v1/projects/{key}/configuration removing a repo not in use succeeds."""
    repository = _InMemoryProjectRepository()
    # Project has two repos; we'll remove the second one.
    project = Project(
        key="tenant-a",
        name="Tenant A",
        story_id_prefix="AG3",
        configuration=ProjectConfiguration(
            repo_url="",
            default_branch="main",
            are_url=None,
            default_worker_count=2,
            repositories=["repo-keep", "repo-remove"],
        ),
        archived_at=None,
    )
    repository.save(project)

    def _checker(project_key: str, repos: list[str]) -> list[str]:
        # "repo-remove" is NOT in use — returns empty list
        return []

    routes = ProjectManagementRoutes(
        repository=repository,
        repos_in_use_checker=_checker,
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
    )
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(project_routes=routes),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="PATCH",
        path="/v1/projects/tenant-a/configuration",
        body=json.dumps(
            {"repositories": ["repo-keep"], "op_id": "op-patch-repos-ok-001"}
        ).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-patch-repos-ok"},
    )

    assert response.status_code == HTTPStatus.OK
    saved = repository.get("tenant-a")
    assert saved is not None
    assert saved.configuration.repositories == ["repo-keep"]


def test_patch_project_updates_repositories_via_body_configuration() -> None:
    """PATCH /v1/projects/{key} with configuration.repositories updates repos."""
    repository = _InMemoryProjectRepository()
    repository.save(_project())

    response = _app(repository).handle_request(
        method="PATCH",
        path="/v1/projects/tenant-a",
        body=json.dumps(
            {
                "configuration": {"repositories": ["repo-new"]},
                "op_id": "op-patch-repos",
            },
        ).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-patch-repos"},
    )

    assert response.status_code == HTTPStatus.OK
    project = repository.get("tenant-a")
    assert project is not None
    assert project.configuration.repositories == ["repo-new"]


# ---------------------------------------------------------------------------
# AG3-140 / FK-91 §91.1a Rule 5 — unified idempotency contract on the four
# mutating project routes (create, archive, PATCH detail, PATCH configuration).
# ---------------------------------------------------------------------------


_IDEM_CORR = "req-idem"


def _project_b() -> Project:
    """A second, distinct project (own key + story_id_prefix) for cross-target tests."""
    return Project(
        key="tenant-b",
        name="Tenant B",
        story_id_prefix="TB",
        configuration=ProjectConfiguration.model_validate(_configuration_payload()),
        archived_at=None,
    )


def _create_payload(
    *,
    key: str = "tenant-a",
    name: str = "Tenant A",
    story_id_prefix: str = "AG3",
    op_id: str = "op-create",
) -> dict[str, object]:
    return {
        "key": key,
        "name": name,
        "story_id_prefix": story_id_prefix,
        "configuration": _configuration_payload(),
        "op_id": op_id,
    }


def _request(
    app: ControlPlaneApplication,
    *,
    method: str,
    path: str,
    payload: dict[str, object],
    corr: str = _IDEM_CORR,
) -> HttpResponse:
    return app.handle_request(
        method=method,
        path=path,
        body=json.dumps(payload).encode("utf-8"),
        request_headers={"X-Correlation-Id": corr},
    )


def _preclaim(
    guard: InMemoryInflightIdempotencyGuard,
    *,
    op_id: str,
    operation_kind: str,
    project_key: str = "tenant-a",
) -> None:
    """Leave a live ``claimed`` row for ``op_id`` (models a concurrent caller)."""
    guard.claim(
        IdempotencyRequest(
            op_id=op_id,
            operation_kind=operation_kind,
            body_hash="preclaimed-hash",
            project_key=project_key,
            story_id=None,
            correlation_id=_IDEM_CORR,
        )
    )


class TestCreateIdempotency:
    def test_create_missing_op_id_returns_422(self) -> None:
        repository = _InMemoryProjectRepository()
        payload = _create_payload()
        del payload["op_id"]
        resp = _request(
            _app_with_guard(repository, InMemoryInflightIdempotencyGuard()),
            method="POST",
            path="/v1/projects",
            payload=payload,
        )
        assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert _json_body(resp.body)["error_code"] == "invalid_project_create_payload"

    def test_create_replay_returns_stored_result_and_runs_once(self) -> None:
        repository = _InMemoryProjectRepository()
        app = _app_with_guard(repository, InMemoryInflightIdempotencyGuard())
        payload = _create_payload(op_id="op-create-replay")
        with patch.object(repository, "save", wraps=repository.save) as save_spy:
            first = _request(app, method="POST", path="/v1/projects", payload=payload)
            second = _request(app, method="POST", path="/v1/projects", payload=payload)
        assert first.status_code == HTTPStatus.CREATED
        # Re-execution would 409 (duplicate key); a 201 on the second call proves
        # the stored result was replayed rather than re-run.
        assert second.status_code == HTTPStatus.CREATED
        assert first.body == second.body
        assert save_spy.call_count == 1
        assert len(repository.list(include_archived=True)) == 1

    def test_create_same_op_id_different_body_returns_409_mismatch(self) -> None:
        repository = _InMemoryProjectRepository()
        app = _app_with_guard(repository, InMemoryInflightIdempotencyGuard())
        first = _request(
            app,
            method="POST",
            path="/v1/projects",
            payload=_create_payload(name="Tenant A", op_id="op-create-mismatch"),
        )
        assert first.status_code == HTTPStatus.CREATED
        second = _request(
            app,
            method="POST",
            path="/v1/projects",
            payload=_create_payload(name="Tenant Renamed", op_id="op-create-mismatch"),
        )
        assert second.status_code == HTTPStatus.CONFLICT
        assert _json_body(second.body)["error_code"] == "idempotency_mismatch"

    def test_create_in_flight_returns_409_operation_in_flight(self) -> None:
        repository = _InMemoryProjectRepository()
        guard = InMemoryInflightIdempotencyGuard()
        _preclaim(
            guard,
            op_id="op-create-inflight",
            operation_kind="project_create",
            project_key="tenant-a",
        )
        resp = _request(
            _app_with_guard(repository, guard),
            method="POST",
            path="/v1/projects",
            payload=_create_payload(op_id="op-create-inflight"),
        )
        assert resp.status_code == HTTPStatus.CONFLICT
        assert _json_body(resp.body)["error_code"] == "operation_in_flight"

    def test_create_replay_after_failure_returns_stored_409_once(self) -> None:
        """AC8: a deterministic domain 4xx (duplicate-create) is stored and replayed.

        The second call returns the SAME 409 and ``_do_create`` (which reads the
        repository) runs exactly once — the replay never re-enters the mutation.
        """
        repository = _InMemoryProjectRepository()
        repository.save(_project())  # tenant-a already exists -> create conflicts
        app = _app_with_guard(repository, InMemoryInflightIdempotencyGuard())
        payload = _create_payload(op_id="op-create-dup-fail")
        with patch.object(repository, "get", wraps=repository.get) as get_spy:
            first = _request(app, method="POST", path="/v1/projects", payload=payload)
            second = _request(app, method="POST", path="/v1/projects", payload=payload)
        assert first.status_code == HTTPStatus.CONFLICT
        assert second.status_code == HTTPStatus.CONFLICT
        assert _json_body(second.body)["error_code"] == "project_key_conflict"
        assert first.body == second.body
        # _do_create read the repository exactly once; the replay short-circuited.
        assert get_spy.call_count == 1


class TestArchiveIdempotency:
    def test_archive_missing_op_id_returns_422(self) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        resp = _request(
            _app_with_guard(repository, InMemoryInflightIdempotencyGuard()),
            method="POST",
            path="/v1/projects/tenant-a/archive",
            payload={},
        )
        assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert _json_body(resp.body)["error_code"] == "invalid_project_archive_payload"

    def test_archive_replay_returns_stored_result_and_runs_once(self) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        app = _app_with_guard(repository, InMemoryInflightIdempotencyGuard())
        payload: dict[str, object] = {"op_id": "op-archive-replay"}
        path = "/v1/projects/tenant-a/archive"
        with patch.object(repository, "save", wraps=repository.save) as save_spy:
            first = _request(app, method="POST", path=path, payload=payload)
            second = _request(app, method="POST", path=path, payload=payload)
        assert first.status_code == HTTPStatus.OK
        # Re-execution would 409 project_already_archived; a 200 proves replay.
        assert second.status_code == HTTPStatus.OK
        assert first.body == second.body
        assert save_spy.call_count == 1

    def test_archive_same_op_id_different_body_returns_409_mismatch(self) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        app = _app_with_guard(repository, InMemoryInflightIdempotencyGuard())
        path = "/v1/projects/tenant-a/archive"
        first = _request(
            app, method="POST", path=path, payload={"op_id": "op-archive-mismatch"}
        )
        assert first.status_code == HTTPStatus.OK
        second = _request(
            app,
            method="POST",
            path=path,
            payload={
                "op_id": "op-archive-mismatch",
                "archived_at": "2020-01-01T00:00:00+00:00",
            },
        )
        assert second.status_code == HTTPStatus.CONFLICT
        assert _json_body(second.body)["error_code"] == "idempotency_mismatch"

    def test_archive_same_op_id_different_project_returns_409_mismatch(self) -> None:
        """Cross-target: the URL-path project key is folded into the body-hash, so
        the same op_id + identical body against a DIFFERENT project fails closed."""
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        repository.save(_project_b())
        app = _app_with_guard(repository, InMemoryInflightIdempotencyGuard())
        payload: dict[str, object] = {"op_id": "op-archive-crosstarget"}
        first = _request(
            app, method="POST", path="/v1/projects/tenant-a/archive", payload=payload
        )
        assert first.status_code == HTTPStatus.OK
        second = _request(
            app, method="POST", path="/v1/projects/tenant-b/archive", payload=payload
        )
        assert second.status_code == HTTPStatus.CONFLICT
        assert _json_body(second.body)["error_code"] == "idempotency_mismatch"
        # tenant-b was NOT archived by the wrong-target replay.
        tenant_b = repository.get("tenant-b")
        assert tenant_b is not None
        assert tenant_b.archived_at is None

    def test_archive_in_flight_returns_409_operation_in_flight(self) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        guard = InMemoryInflightIdempotencyGuard()
        _preclaim(guard, op_id="op-archive-inflight", operation_kind="project_archive")
        resp = _request(
            _app_with_guard(repository, guard),
            method="POST",
            path="/v1/projects/tenant-a/archive",
            payload={"op_id": "op-archive-inflight"},
        )
        assert resp.status_code == HTTPStatus.CONFLICT
        assert _json_body(resp.body)["error_code"] == "operation_in_flight"


class TestPatchDetailIdempotency:
    def test_patch_detail_missing_op_id_returns_422(self) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        resp = _request(
            _app_with_guard(repository, InMemoryInflightIdempotencyGuard()),
            method="PATCH",
            path="/v1/projects/tenant-a",
            payload={"name": "New Name"},
        )
        assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert _json_body(resp.body)["error_code"] == "invalid_project_update_payload"

    def test_patch_detail_replay_returns_stored_result_and_runs_once(self) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        app = _app_with_guard(repository, InMemoryInflightIdempotencyGuard())
        payload: dict[str, object] = {"name": "Tenant Alpha", "op_id": "op-patch-replay"}
        path = "/v1/projects/tenant-a"
        with patch.object(repository, "save", wraps=repository.save) as save_spy:
            first = _request(app, method="PATCH", path=path, payload=payload)
            second = _request(app, method="PATCH", path=path, payload=payload)
        assert first.status_code == HTTPStatus.OK
        assert second.status_code == HTTPStatus.OK
        assert first.body == second.body
        # Idempotent update — single execution is proven by the save spy.
        assert save_spy.call_count == 1
        updated = repository.get("tenant-a")
        assert updated is not None and updated.name == "Tenant Alpha"

    def test_patch_detail_same_op_id_different_body_returns_409_mismatch(self) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        app = _app_with_guard(repository, InMemoryInflightIdempotencyGuard())
        path = "/v1/projects/tenant-a"
        first = _request(
            app,
            method="PATCH",
            path=path,
            payload={"name": "Alpha", "op_id": "op-patch-mismatch"},
        )
        assert first.status_code == HTTPStatus.OK
        second = _request(
            app,
            method="PATCH",
            path=path,
            payload={"name": "Beta", "op_id": "op-patch-mismatch"},
        )
        assert second.status_code == HTTPStatus.CONFLICT
        assert _json_body(second.body)["error_code"] == "idempotency_mismatch"

    def test_patch_detail_same_op_id_different_project_returns_409_mismatch(self) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        repository.save(_project_b())
        app = _app_with_guard(repository, InMemoryInflightIdempotencyGuard())
        payload: dict[str, object] = {"name": "Renamed", "op_id": "op-patch-crosstarget"}
        first = _request(
            app, method="PATCH", path="/v1/projects/tenant-a", payload=payload
        )
        assert first.status_code == HTTPStatus.OK
        second = _request(
            app, method="PATCH", path="/v1/projects/tenant-b", payload=payload
        )
        assert second.status_code == HTTPStatus.CONFLICT
        assert _json_body(second.body)["error_code"] == "idempotency_mismatch"
        tenant_b = repository.get("tenant-b")
        assert tenant_b is not None and tenant_b.name == "Tenant B"

    def test_patch_detail_in_flight_returns_409_operation_in_flight(self) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        guard = InMemoryInflightIdempotencyGuard()
        _preclaim(guard, op_id="op-patch-inflight", operation_kind="project_update")
        resp = _request(
            _app_with_guard(repository, guard),
            method="PATCH",
            path="/v1/projects/tenant-a",
            payload={"name": "New", "op_id": "op-patch-inflight"},
        )
        assert resp.status_code == HTTPStatus.CONFLICT
        assert _json_body(resp.body)["error_code"] == "operation_in_flight"


class TestPatchConfigurationIdempotency:
    def test_patch_configuration_missing_op_id_returns_422(self) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        resp = _request(
            _app_with_guard(repository, InMemoryInflightIdempotencyGuard()),
            method="PATCH",
            path="/v1/projects/tenant-a/configuration",
            payload={"default_worker_count": 4},
        )
        assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert (
            _json_body(resp.body)["error_code"]
            == "invalid_project_configuration_patch"
        )

    def test_patch_configuration_replay_returns_stored_result_and_runs_once(
        self,
    ) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        app = _app_with_guard(repository, InMemoryInflightIdempotencyGuard())
        payload: dict[str, object] = {
            "default_worker_count": 4,
            "op_id": "op-config-replay",
        }
        path = "/v1/projects/tenant-a/configuration"
        with patch.object(repository, "save", wraps=repository.save) as save_spy:
            first = _request(app, method="PATCH", path=path, payload=payload)
            second = _request(app, method="PATCH", path=path, payload=payload)
        assert first.status_code == HTTPStatus.OK
        assert second.status_code == HTTPStatus.OK
        assert first.body == second.body
        assert save_spy.call_count == 1
        updated = repository.get("tenant-a")
        assert updated is not None
        assert updated.configuration.default_worker_count == 4

    def test_patch_configuration_same_op_id_different_body_returns_409_mismatch(
        self,
    ) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        app = _app_with_guard(repository, InMemoryInflightIdempotencyGuard())
        path = "/v1/projects/tenant-a/configuration"
        first = _request(
            app,
            method="PATCH",
            path=path,
            payload={"default_worker_count": 4, "op_id": "op-config-mismatch"},
        )
        assert first.status_code == HTTPStatus.OK
        second = _request(
            app,
            method="PATCH",
            path=path,
            payload={"default_worker_count": 8, "op_id": "op-config-mismatch"},
        )
        assert second.status_code == HTTPStatus.CONFLICT
        assert _json_body(second.body)["error_code"] == "idempotency_mismatch"

    def test_patch_configuration_same_op_id_different_project_returns_409_mismatch(
        self,
    ) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        repository.save(_project_b())
        app = _app_with_guard(repository, InMemoryInflightIdempotencyGuard())
        payload: dict[str, object] = {
            "default_worker_count": 4,
            "op_id": "op-config-crosstarget",
        }
        first = _request(
            app,
            method="PATCH",
            path="/v1/projects/tenant-a/configuration",
            payload=payload,
        )
        assert first.status_code == HTTPStatus.OK
        second = _request(
            app,
            method="PATCH",
            path="/v1/projects/tenant-b/configuration",
            payload=payload,
        )
        assert second.status_code == HTTPStatus.CONFLICT
        assert _json_body(second.body)["error_code"] == "idempotency_mismatch"
        # tenant-b configuration untouched by the wrong-target replay.
        tenant_b = repository.get("tenant-b")
        assert tenant_b is not None
        assert tenant_b.configuration.default_worker_count == 2

    def test_patch_configuration_in_flight_returns_409_operation_in_flight(
        self,
    ) -> None:
        repository = _InMemoryProjectRepository()
        repository.save(_project())
        guard = InMemoryInflightIdempotencyGuard()
        _preclaim(
            guard,
            op_id="op-config-inflight",
            operation_kind="project_configuration_update",
        )
        resp = _request(
            _app_with_guard(repository, guard),
            method="PATCH",
            path="/v1/projects/tenant-a/configuration",
            payload={"default_worker_count": 4, "op_id": "op-config-inflight"},
        )
        assert resp.status_code == HTTPStatus.CONFLICT
        assert _json_body(resp.body)["error_code"] == "operation_in_flight"


# ---------------------------------------------------------------------------
# AG3-140 Codex r2: the finalize-CAS-loss (#1) and pre-outcome-exception (#2)
# window invariants, proven at the ROUTE level.
# ---------------------------------------------------------------------------


class _FinalizeAlwaysFalseGuard(InMemoryInflightIdempotencyGuard):
    """A guard whose finalize CAS always loses (models an admin-abort takeover)."""

    def finalize(self, request, claim, result_payload) -> bool:  # type: ignore[override]
        return False


class _RaiseOnceSaveRepo(_InMemoryProjectRepository):
    """A repo whose FIRST ``save`` raises a transient infra error (pre-commit)."""

    def __init__(self) -> None:
        super().__init__()
        self._raised = False

    def save(self, project: Project) -> None:
        if not self._raised:
            self._raised = True
            raise RuntimeError("transient database error before commit")
        super().save(project)


class TestCreateWindowInvariants:
    def test_create_finalize_lost_does_not_return_success(self) -> None:
        """Codex r2 #1: a finalize CAS loss must NOT surface a 201 committed."""
        repository = _InMemoryProjectRepository()
        app = _app_with_guard(repository, _FinalizeAlwaysFalseGuard())
        with patch.object(repository, "save", wraps=repository.save) as save_spy:
            resp = _request(
                app,
                method="POST",
                path="/v1/projects",
                payload=_create_payload(op_id="op-finalize-lost"),
            )
        assert save_spy.call_count == 1  # the mutation ran
        # ... but the record does NOT hold our result (claim lost) -> fail-closed
        # 409, never a 201 committed success.
        assert resp.status_code != HTTPStatus.CREATED
        assert resp.status_code == HTTPStatus.CONFLICT

    def test_create_pre_outcome_exception_releases_claim_and_retry_succeeds(self) -> None:
        """Codex r2 #2: a pre-outcome exception releases the claim; a retry re-runs."""
        guard = InMemoryInflightIdempotencyGuard()
        routes = ProjectManagementRoutes(
            repository=_RaiseOnceSaveRepo(),
            repos_in_use_checker=_no_repos_in_use,
            idempotency_guard=guard,
        )
        payload = _create_payload(op_id="op-pre-outcome-boom")

        # First attempt: the durable save raises before commit -> the owner-scoped
        # claim is RELEASED and the exception propagates (transport-level fault).
        try:
            routes._handle_create(payload, _IDEM_CORR)  # noqa: SLF001
        except RuntimeError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected the transient save exception to propagate")

        # Retry with the SAME op_id: the released claim is re-claimable, so the
        # mutation re-executes and succeeds -- NOT stuck operation_in_flight.
        retry = routes._handle_create(payload, _IDEM_CORR)  # noqa: SLF001
        assert retry.status_code == HTTPStatus.CREATED
