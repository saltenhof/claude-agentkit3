"""HTTP-layer tests for the Edge-Push-Gate online-ownership check (AG3-147 AC6).

Mirrors ``test_push_freshness_http.py``: a fake ``ControlPlaneRuntimeService``
wired directly into ``ControlPlaneApplication`` (no database). Covers the route
wiring + response, the 400 on missing query params, and the Postgres-only
fail-closed 503.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import cast

from tests.story_read_port_stub import StubStoryReadPort

from agentkit.backend.control_plane.http import ControlPlaneApplication, HttpResponse
from agentkit.backend.control_plane.models import PushOwnershipConfirmation
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.exceptions import ConfigError
from agentkit.backend.story.service import StoryService


class _FakeStoryService(StoryService):
    def __init__(self) -> None:
        super().__init__(repository=StubStoryReadPort())


class _NoopTenantScopeMiddleware:
    def validate(self, *, method: str, route_path: str, correlation_id: str) -> None:
        return None


class _FakePushOwnershipRuntimeService(ControlPlaneRuntimeService):
    def __init__(
        self,
        *,
        owner_confirmed: bool = True,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self._owner_confirmed = owner_confirmed
        self.error = error
        self.calls: list[tuple[str, str, str, str]] = []

    def confirm_push_ownership(
        self, run_id: str, *, project_key: str, story_id: str, session_id: str,
    ) -> PushOwnershipConfirmation:
        if self.error is not None:
            raise self.error
        self.calls.append((run_id, project_key, story_id, session_id))
        return PushOwnershipConfirmation(
            run_id=run_id, owner_confirmed=self._owner_confirmed, detail="fake",
        )


def _app(runtime: ControlPlaneRuntimeService) -> ControlPlaneApplication:
    return ControlPlaneApplication(
        runtime_service=runtime,
        story_service=_FakeStoryService(),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )


def _json_body(response: HttpResponse) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(response.body))


def test_get_push_ownership_returns_the_confirmation() -> None:
    runtime = _FakePushOwnershipRuntimeService(owner_confirmed=True)
    app = _app(runtime)

    response = app.handle_request(
        method="GET",
        path=(
            "/v1/project-edge/story-runs/run-1/push-ownership"
            "?project_key=tenant-a&story_id=AG3-147&session_id=sess-A"
        ),
        body=b"",
    )

    assert response.status_code == HTTPStatus.OK
    body = _json_body(response)
    assert body["owner_confirmed"] is True
    assert body["run_id"] == "run-1"
    assert runtime.calls == [("run-1", "tenant-a", "AG3-147", "sess-A")]


def test_get_push_ownership_denied_owner_surfaces_false() -> None:
    runtime = _FakePushOwnershipRuntimeService(owner_confirmed=False)
    app = _app(runtime)

    response = app.handle_request(
        method="GET",
        path=(
            "/v1/project-edge/story-runs/run-1/push-ownership"
            "?project_key=tenant-a&story_id=AG3-147&session_id=sess-A"
        ),
        body=b"",
    )

    assert response.status_code == HTTPStatus.OK
    assert _json_body(response)["owner_confirmed"] is False


def test_get_push_ownership_missing_query_params_returns_400() -> None:
    app = _app(_FakePushOwnershipRuntimeService())

    response = app.handle_request(
        method="GET",
        path="/v1/project-edge/story-runs/run-1/push-ownership?project_key=tenant-a",
        body=b"",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert _json_body(response)["error_code"] == "invalid_push_ownership_query"


def test_get_push_ownership_non_postgres_backend_fails_closed_503() -> None:
    """The gate check is Postgres-only (K5); a ConfigError -> 503."""
    runtime = _FakePushOwnershipRuntimeService(
        error=ConfigError("Postgres state backend required")
    )
    app = _app(runtime)

    response = app.handle_request(
        method="GET",
        path=(
            "/v1/project-edge/story-runs/run-1/push-ownership"
            "?project_key=tenant-a&story_id=AG3-147&session_id=sess-A"
        ),
        body=b"",
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert _json_body(response)["error_code"] == "push_ownership_unavailable"
