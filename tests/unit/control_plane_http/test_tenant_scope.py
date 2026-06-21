"""Unit tests for control_plane_http.tenant_scope (AG3-090, AC3).

Covers:
  - unknown project_key -> 404 project_not_found
  - archived project + mutation method -> 403 forbidden
  - valid project GET -> passthrough (None)
  - valid project mutation -> passthrough (None)
  - non-project-scoped path -> passthrough (None) without repository call
  - repo lookup exception -> 503 project_lookup_unavailable
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus

from agentkit.backend.control_plane_http.tenant_scope import TenantScopeMiddleware
from agentkit.backend.project_management.entities import Project, ProjectConfiguration

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

_LIVE_PROJECT = Project(
    key="myproj",
    name="My Project",
    story_id_prefix="MYP",
    configuration=ProjectConfiguration(
        repo_url="https://github.com/org/myproj",
        default_branch="main",
        default_worker_count=2,
        repositories=["https://github.com/org/myproj"],
    ),
)

_ARCHIVED_PROJECT = Project(
    key="archived",
    name="Archived Project",
    story_id_prefix="ARC",
    configuration=ProjectConfiguration(
        repo_url="https://github.com/org/archived",
        default_branch="main",
        default_worker_count=1,
        repositories=["https://github.com/org/archived"],
    ),
    archived_at=datetime(2026, 1, 1, tzinfo=UTC),
)


class _FakeRepository:
    """Configurable in-memory project repository stub."""

    def __init__(self, projects: list[Project]) -> None:
        self._projects = {p.key: p for p in projects}
        self.call_count = 0

    def get(self, key: str) -> Project | None:
        self.call_count += 1
        return self._projects.get(key)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return list(self._projects.values())

    def save(self, project: Project) -> None:
        self._projects[project.key] = project


class _FailingRepository:
    """Repository that always raises on get()."""

    def get(self, key: str) -> Project | None:
        raise RuntimeError("Database is down")

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return []

    def save(self, project: Project) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_body(response: object) -> object:
    from agentkit.backend.control_plane_http.app import HttpResponse

    assert isinstance(response, HttpResponse)
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# Non-project-scoped path: always passthrough, no repo call
# ---------------------------------------------------------------------------


def test_non_project_path_passes_without_repo_call() -> None:
    """Paths not starting with /v1/projects/{key}/ skip the middleware."""
    repo = _FakeRepository([_LIVE_PROJECT])
    middleware = TenantScopeMiddleware(repository=repo)  # type: ignore[arg-type]

    result = middleware.validate(
        method="GET",
        route_path="/v1/telemetry/events",
        correlation_id="corr-1",
    )
    assert result is None
    assert repo.call_count == 0


def test_healthz_path_passes_without_repo_call() -> None:
    repo = _FakeRepository([])
    middleware = TenantScopeMiddleware(repository=repo)  # type: ignore[arg-type]

    result = middleware.validate(
        method="GET",
        route_path="/healthz",
        correlation_id="corr-2",
    )
    assert result is None
    assert repo.call_count == 0


# ---------------------------------------------------------------------------
# Unknown project -> 404
# ---------------------------------------------------------------------------


def test_unknown_project_get_returns_404() -> None:
    repo = _FakeRepository([_LIVE_PROJECT])
    middleware = TenantScopeMiddleware(repository=repo)  # type: ignore[arg-type]

    result = middleware.validate(
        method="GET",
        route_path="/v1/projects/no-such-project/phases",
        correlation_id="corr-3",
    )
    from agentkit.backend.control_plane_http.app import HttpResponse

    assert isinstance(result, HttpResponse)
    assert result.status_code == int(HTTPStatus.NOT_FOUND)
    body = _json_body(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "project_not_found"
    assert "no-such-project" in body["error"]
    assert body["correlation_id"] == "corr-3"


def test_unknown_project_post_returns_404() -> None:
    repo = _FakeRepository([_LIVE_PROJECT])
    middleware = TenantScopeMiddleware(repository=repo)  # type: ignore[arg-type]

    result = middleware.validate(
        method="POST",
        route_path="/v1/projects/no-such-project/stories",
        correlation_id="corr-4",
    )
    from agentkit.backend.control_plane_http.app import HttpResponse

    assert isinstance(result, HttpResponse)
    assert result.status_code == int(HTTPStatus.NOT_FOUND)


# ---------------------------------------------------------------------------
# Archived project + mutation -> 403
# ---------------------------------------------------------------------------


def test_archived_project_post_returns_403() -> None:
    repo = _FakeRepository([_ARCHIVED_PROJECT])
    middleware = TenantScopeMiddleware(repository=repo)  # type: ignore[arg-type]

    result = middleware.validate(
        method="POST",
        route_path="/v1/projects/archived/stories",
        correlation_id="corr-5",
    )
    from agentkit.backend.control_plane_http.app import HttpResponse

    assert isinstance(result, HttpResponse)
    assert result.status_code == int(HTTPStatus.FORBIDDEN)
    body = _json_body(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "forbidden"
    assert body["correlation_id"] == "corr-5"


def test_archived_project_put_returns_403() -> None:
    repo = _FakeRepository([_ARCHIVED_PROJECT])
    middleware = TenantScopeMiddleware(repository=repo)  # type: ignore[arg-type]

    result = middleware.validate(
        method="PUT",
        route_path="/v1/projects/archived/stories/ARC-001/fields/title",
        correlation_id="corr-6",
    )
    from agentkit.backend.control_plane_http.app import HttpResponse

    assert isinstance(result, HttpResponse)
    assert result.status_code == int(HTTPStatus.FORBIDDEN)


def test_archived_project_patch_returns_403() -> None:
    repo = _FakeRepository([_ARCHIVED_PROJECT])
    middleware = TenantScopeMiddleware(repository=repo)  # type: ignore[arg-type]

    result = middleware.validate(
        method="PATCH",
        route_path="/v1/projects/archived/stories/ARC-001",
        correlation_id="corr-7",
    )
    from agentkit.backend.control_plane_http.app import HttpResponse

    assert isinstance(result, HttpResponse)
    assert result.status_code == int(HTTPStatus.FORBIDDEN)


def test_archived_project_delete_returns_403() -> None:
    repo = _FakeRepository([_ARCHIVED_PROJECT])
    middleware = TenantScopeMiddleware(repository=repo)  # type: ignore[arg-type]

    result = middleware.validate(
        method="DELETE",
        route_path="/v1/projects/archived/stories/ARC-001",
        correlation_id="corr-8",
    )
    from agentkit.backend.control_plane_http.app import HttpResponse

    assert isinstance(result, HttpResponse)
    assert result.status_code == int(HTTPStatus.FORBIDDEN)


# ---------------------------------------------------------------------------
# Archived project + GET -> passthrough (read-only access allowed)
# ---------------------------------------------------------------------------


def test_archived_project_get_passes_through() -> None:
    """Archived projects: GET is allowed for observability."""
    repo = _FakeRepository([_ARCHIVED_PROJECT])
    middleware = TenantScopeMiddleware(repository=repo)  # type: ignore[arg-type]

    result = middleware.validate(
        method="GET",
        route_path="/v1/projects/archived/stories",
        correlation_id="corr-9",
    )
    assert result is None


# ---------------------------------------------------------------------------
# Valid live project -> passthrough
# ---------------------------------------------------------------------------


def test_valid_project_get_passes_through() -> None:
    repo = _FakeRepository([_LIVE_PROJECT])
    middleware = TenantScopeMiddleware(repository=repo)  # type: ignore[arg-type]

    result = middleware.validate(
        method="GET",
        route_path="/v1/projects/myproj/phases",
        correlation_id="corr-10",
    )
    assert result is None


def test_valid_project_post_passes_through() -> None:
    repo = _FakeRepository([_LIVE_PROJECT])
    middleware = TenantScopeMiddleware(repository=repo)  # type: ignore[arg-type]

    result = middleware.validate(
        method="POST",
        route_path="/v1/projects/myproj/stories",
        correlation_id="corr-11",
    )
    assert result is None


# ---------------------------------------------------------------------------
# Repo exception -> 503
# ---------------------------------------------------------------------------


def test_repo_exception_returns_503() -> None:
    """Repository unavailability must produce a structured 503, never a 500."""
    middleware = TenantScopeMiddleware(repository=_FailingRepository())  # type: ignore[arg-type]

    result = middleware.validate(
        method="GET",
        route_path="/v1/projects/myproj/phases",
        correlation_id="corr-12",
    )
    from agentkit.backend.control_plane_http.app import HttpResponse

    assert isinstance(result, HttpResponse)
    assert result.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)
    body = _json_body(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "project_lookup_unavailable"


# ---------------------------------------------------------------------------
# X-Correlation-Id header on error responses
# ---------------------------------------------------------------------------


def test_404_carries_correlation_id_header() -> None:
    repo = _FakeRepository([])
    middleware = TenantScopeMiddleware(repository=repo)  # type: ignore[arg-type]

    result = middleware.validate(
        method="GET",
        route_path="/v1/projects/ghost/phases",
        correlation_id="trace-abc",
    )
    from agentkit.backend.control_plane_http.app import HttpResponse

    assert isinstance(result, HttpResponse)
    header_map = dict(result.headers)
    assert header_map.get("X-Correlation-Id") == "trace-abc"
