from __future__ import annotations

import json
from http import HTTPStatus

from agentkit.control_plane.http import ControlPlaneApplication
from agentkit.control_plane_http.app import ControlPlaneApplicationRoutes
from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.project_management.http.routes import ProjectManagementRoutes


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
                from agentkit.project_management.errors import (
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
    from agentkit.project_management.http.routes import _no_repos_in_use
    from agentkit.project_management.service import ProjectDetailService

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
            ),
        ),
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
        body=json.dumps({"story_id_prefix": "OTHER"}).encode("utf-8"),
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
    field behind a model-validator default.  The strict schema (Befund 1
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
        body=json.dumps({"repositories": ["repo-a", "repo-b"]}).encode("utf-8"),
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
    )
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(project_routes=routes),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="PATCH",
        path="/v1/projects/tenant-a/configuration",
        body=json.dumps({"repositories": ["new-repo"]}).encode("utf-8"),
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
    )
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(project_routes=routes),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="PATCH",
        path="/v1/projects/tenant-a/configuration",
        body=json.dumps({"repositories": ["repo-keep"]}).encode("utf-8"),
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
