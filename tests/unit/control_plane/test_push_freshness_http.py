"""HTTP-layer tests for the push-freshness read surface (FK-10 §10.2.4b, AG3-147).

Mirrors ``test_edge_commands_http.py``: a fake ``ControlPlaneRuntimeService``
wired directly into ``ControlPlaneApplication`` (no database). Covers AC5 (the
read-model route wiring + response, the 400 on missing query params, and the
Postgres-only fail-closed 503).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from typing import cast

from tests.story_read_port_stub import StubStoryReadPort

from agentkit.backend.control_plane.http import ControlPlaneApplication, HttpResponse
from agentkit.backend.control_plane.models import (
    PushFreshnessListResponse,
    PushFreshnessView,
)
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.exceptions import ConfigError
from agentkit.backend.story.service import StoryService

_NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


class _FakeStoryService(StoryService):
    def __init__(self) -> None:
        super().__init__(repository=StubStoryReadPort())


class _NoopTenantScopeMiddleware:
    def validate(self, *, method: str, route_path: str, correlation_id: str) -> None:
        return None


class _FakePushFreshnessRuntimeService(ControlPlaneRuntimeService):
    def __init__(
        self,
        *,
        response: PushFreshnessListResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self._response = response or PushFreshnessListResponse()
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def list_push_freshness(
        self, run_id: str, *, project_key: str, story_id: str,
    ) -> PushFreshnessListResponse:
        if self.error is not None:
            raise self.error
        self.calls.append((run_id, project_key, story_id))
        return self._response


def _app(runtime: ControlPlaneRuntimeService) -> ControlPlaneApplication:
    return ControlPlaneApplication(
        runtime_service=runtime,
        story_service=_FakeStoryService(),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )


def _json_body(response: HttpResponse) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(response.body))


def test_get_push_freshness_returns_the_wired_response() -> None:
    runtime = _FakePushFreshnessRuntimeService(
        response=PushFreshnessListResponse(
            freshness=[
                PushFreshnessView(
                    repo_id="repo-a",
                    last_reported_head_sha="a" * 40,
                    last_pushed_head_sha="a" * 40,
                    last_reported_at=_NOW,
                    backlog=False,
                ),
                PushFreshnessView(
                    repo_id="repo-b",
                    last_reported_head_sha="b" * 40,
                    last_pushed_head_sha=None,
                    last_reported_at=_NOW,
                    backlog=True,
                    backlog_detail="behind remote",
                ),
            ]
        )
    )
    app = _app(runtime)

    response = app.handle_request(
        method="GET",
        path=(
            "/v1/project-edge/story-runs/run-1/push-freshness"
            "?project_key=tenant-a&story_id=AG3-147"
        ),
        body=b"",
    )

    assert response.status_code == HTTPStatus.OK
    body = _json_body(response)
    freshness = cast("list[dict[str, object]]", body["freshness"])
    assert len(freshness) == 2
    assert freshness[0]["repo_id"] == "repo-a"
    assert freshness[1]["backlog"] is True
    assert runtime.calls == [("run-1", "tenant-a", "AG3-147")]


def test_get_push_freshness_missing_query_params_returns_400() -> None:
    app = _app(_FakePushFreshnessRuntimeService())

    response = app.handle_request(
        method="GET",
        path="/v1/project-edge/story-runs/run-1/push-freshness",
        body=b"",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert _json_body(response)["error_code"] == "invalid_push_freshness_query"


def test_get_push_freshness_missing_story_id_only_returns_400() -> None:
    app = _app(_FakePushFreshnessRuntimeService())

    response = app.handle_request(
        method="GET",
        path="/v1/project-edge/story-runs/run-1/push-freshness?project_key=tenant-a",
        body=b"",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_get_push_freshness_non_postgres_backend_fails_closed_503() -> None:
    """AC5/AC13: the read surface is Postgres-only; a ConfigError -> 503."""
    runtime = _FakePushFreshnessRuntimeService(
        error=ConfigError("Postgres state backend required")
    )
    app = _app(runtime)

    response = app.handle_request(
        method="GET",
        path=(
            "/v1/project-edge/story-runs/run-1/push-freshness"
            "?project_key=tenant-a&story_id=AG3-147"
        ),
        body=b"",
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert _json_body(response)["error_code"] == "push_freshness_unavailable"
