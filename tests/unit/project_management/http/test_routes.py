from __future__ import annotations

import json
from http import HTTPStatus

from agentkit.control_plane.http import ControlPlaneApplication
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


def _app(repository: _InMemoryProjectRepository) -> ControlPlaneApplication:
    return ControlPlaneApplication(
        project_routes=ProjectManagementRoutes(repository),
    )


def _configuration_payload() -> dict[str, object]:
    return {
        "repo_url": "https://example.test/repo.git",
        "default_branch": "main",
        "are_url": None,
        "default_worker_count": 2,
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
    assert _json_body(response.body)["projects"] == [
        {
            "key": "tenant-a",
            "name": "Tenant A",
            "story_id_prefix": "AG3",
            "configuration": _configuration_payload(),
            "archived_at": None,
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
    assert project_payload["key"] == "tenant-a"


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
