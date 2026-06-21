from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.auth.middleware import AuthMiddleware
from agentkit.backend.auth.sessions import InMemorySessionStore
from agentkit.backend.control_plane.http import ControlPlaneApplication, HttpResponse
from agentkit.backend.control_plane_http.app import ControlPlaneApplicationRoutes
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.http.routes import TelemetryRoutes

if TYPE_CHECKING:
    from agentkit.backend.auth.entities import ProjectApiToken


class _InMemoryTokenRepository:
    def get(self, token_id: str) -> ProjectApiToken | None:
        del token_id
        return None

    def get_by_hash(self, token_hash: str) -> ProjectApiToken | None:
        del token_hash
        return None

    def list_for_project(self, project_key: str) -> list[ProjectApiToken]:
        del project_key
        return []

    def save(self, token: ProjectApiToken) -> None:
        del token

    def revoke(self, project_key: str, token_id: str) -> None:
        del project_key, token_id


class _NoopTenantScopeMiddleware:
    """Passthrough stub: all project-scoped paths pass without DB access (AG3-090)."""

    def validate(self, *, method: str, route_path: str, correlation_id: str) -> None:
        return None


class _FakeProjectEventSource:
    def __init__(self) -> None:
        self.records = [
            _record(project_key="tenant-a", event_id="evt-a", topic="stories"),
            _record(project_key="tenant-b", event_id="evt-b", topic="stories"),
            _record(project_key="tenant-a", event_id="evt-g", topic="governance"),
        ]
        self.project_keys: list[str] = []

    def events_for_project(
        self,
        project_key: str,
        *,
        limit: int = 200,
    ) -> list[ExecutionEventRecord]:
        del limit
        self.project_keys.append(project_key)
        return [record for record in self.records if record.project_key == project_key]


def _record(
    *,
    project_key: str,
    event_id: str,
    topic: str,
) -> ExecutionEventRecord:
    return ExecutionEventRecord(
        project_key=project_key,
        story_id="AG3-100",
        run_id="run-1",
        event_id=event_id,
        event_type="agent_start",
        occurred_at=datetime(2026, 5, 4, 10, 0, tzinfo=UTC),
        source_component="telemetry",
        severity="info",
        payload={"topic": topic},
    )


def test_project_events_endpoint_returns_sse_stream_and_filters_project() -> None:
    source = _FakeProjectEventSource()
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(telemetry_routes=TelemetryRoutes(source)),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="GET",
        path="/v1/projects/tenant-a/events?topics=stories",
        body=b"",
        request_headers={"X-Correlation-Id": "req-sse"},
    )

    assert response.status_code == HTTPStatus.OK
    assert _header(response, "Content-Type") == "text/event-stream; charset=utf-8"
    assert response.stream is not None
    first_chunk = next(iter(response.stream)).decode("utf-8")
    assert "event: stories" in first_chunk
    assert "evt-a" in first_chunk
    assert "evt-b" not in first_chunk
    assert source.project_keys == ["tenant-a"]


def test_project_events_endpoint_rejects_unknown_topics() -> None:
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            telemetry_routes=TelemetryRoutes(_FakeProjectEventSource())
        ),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="GET",
        path="/v1/projects/tenant-a/events?topics=unknown",
        body=b"",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    body = _json_body(response)
    assert body["error_code"] == "invalid_sse_topics"


def test_project_events_endpoint_requires_auth_when_middleware_is_enabled() -> None:
    sessions = InMemorySessionStore()
    middleware = AuthMiddleware(
        session_store=sessions,
        token_repository=_InMemoryTokenRepository(),
    )
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            telemetry_routes=TelemetryRoutes(_FakeProjectEventSource())
        ),
        auth_middleware=middleware,
    )

    response = app.handle_request(
        method="GET",
        path="/v1/projects/tenant-a/events",
        body=b"",
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def _json_body(response: HttpResponse) -> dict[str, object]:
    body = json.loads(response.body.decode("utf-8"))
    assert isinstance(body, dict)
    return body


def _header(response: HttpResponse, name: str) -> str:
    for key, value in response.headers:
        if key == name:
            return value
    raise AssertionError(f"Missing header {name}")
