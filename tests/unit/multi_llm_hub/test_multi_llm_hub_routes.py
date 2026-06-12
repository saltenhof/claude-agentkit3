from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus

from agentkit.control_plane.http import ControlPlaneApplication
from agentkit.control_plane_http.app import ControlPlaneApplicationRoutes
from agentkit.multi_llm_hub.entities import (
    HubBackendMetric,
    HubBackendName,
    HubBackendSessionStats,
    HubHealth,
    HubMessage,
    HubSession,
    HubSessionLease,
    HubSessionStats,
)
from agentkit.multi_llm_hub.errors import HubUnavailableError
from agentkit.multi_llm_hub.http.routes import MultiLlmHubRoutes


class _FakeHubClient:
    def __init__(self) -> None:
        self.unavailable = False
        self.released: list[tuple[str, str]] = []

    def health(self) -> HubHealth:
        if self.unavailable:
            raise HubUnavailableError("Hub down")
        return HubHealth(
            status="ok",
            version="0.3.0",
            backends={"chatgpt": "ok"},
            persistence="ok",
            uptime_ms=100,
        )

    def pool_status(self) -> list[HubBackendMetric]:
        if self.unavailable:
            raise HubUnavailableError("Hub down")
        return [
            HubBackendMetric(
                name="chatgpt",
                label="ChatGPT",
                status="healthy",
                slots_total=3,
                slots_in_use=1,
                sends=0,
                responses=0,
                errors=0,
                avg_response_ms=None,
                holders=[],
            ),
        ]

    def list_sessions(self, *, include_inactive: bool = False) -> list[HubSession]:
        if self.unavailable:
            raise HubUnavailableError("Hub down")
        return [
            HubSession(
                session_id="s-1",
                owner="main",
                description="Main session",
                llms=["chatgpt"],
                status="active",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                last_activity=datetime(2026, 1, 1, tzinfo=UTC),
                resumable=False,
            ),
        ]

    def acquire(
        self,
        *,
        owner: str,
        description: str,
        llms: list[HubBackendName],
    ) -> HubSessionLease:
        if self.unavailable:
            raise HubUnavailableError("Hub down")
        return HubSessionLease(
            session_id="s-1",
            token="tok",
            llms=["chatgpt"],
            slots={"chatgpt": 0},
        )

    def send(
        self,
        *,
        session_id: str,
        token: str,
        message: str | None = None,
        target: HubBackendName | None = None,
        targets: dict[HubBackendName, str] | None = None,
    ) -> dict[HubBackendName, HubMessage]:
        if self.unavailable:
            raise HubUnavailableError("Hub down")
        return {
            "chatgpt": HubMessage(
                id="m-1",
                session_id=session_id,
                backend="chatgpt",
                role="assistant",
                text=message or "targeted",
                at=datetime(2026, 1, 1, tzinfo=UTC),
                status="ok",
            ),
        }

    def release(self, *, session_id: str, token: str) -> None:
        if self.unavailable:
            raise HubUnavailableError("Hub down")
        self.released.append((session_id, token))

    def resume(self, *, session_id: str) -> HubSessionLease:
        if self.unavailable:
            raise HubUnavailableError("Hub down")
        return HubSessionLease(
            session_id=session_id,
            token="resumed-tok",
            llms=["chatgpt"],
            slots={"chatgpt": 0},
        )

    def session_stats(
        self, *, session_id: str, timeout: float | None = None
    ) -> HubSessionStats:
        del timeout
        if self.unavailable:
            raise HubUnavailableError("Hub down")
        return HubSessionStats(
            session_id=session_id,
            status="released",
            released=True,
            backends=[
                HubBackendSessionStats(
                    backend="chatgpt", message_count=2, answered=True
                ),
            ],
        )


def _app(client: _FakeHubClient) -> ControlPlaneApplication:
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(hub_routes=MultiLlmHubRoutes(client))
    )


def _json_body(response_body: bytes) -> dict[str, object]:
    body = json.loads(response_body.decode("utf-8"))
    assert isinstance(body, dict)
    return body


def test_get_hub_status_returns_health_and_metrics() -> None:
    response = _app(_FakeHubClient()).handle_request(
        method="GET",
        path="/v1/hub/status",
        body=b"",
        request_headers={"X-Correlation-Id": "req-hub-status"},
    )

    body = _json_body(response.body)
    assert response.status_code == HTTPStatus.OK
    assert body["health"] == {
        "status": "ok",
        "version": "0.3.0",
        "backends": {"chatgpt": "ok"},
        "persistence": "ok",
        "uptime_ms": 100,
    }


def test_get_hub_session_stats_returns_stats() -> None:  # AG3-097 AK5
    """The read-only ``/v1/hub/sessions/{id}/stats`` GET route returns stats."""
    response = _app(_FakeHubClient()).handle_request(
        method="GET",
        path="/v1/hub/sessions/s-1/stats",
        body=b"",
        request_headers={"X-Correlation-Id": "req-hub-stats"},
    )

    body = _json_body(response.body)
    assert response.status_code == HTTPStatus.OK
    stats = body["stats"]
    assert isinstance(stats, dict)
    assert stats["session_id"] == "s-1"
    assert stats["released"] is True
    assert stats["backends"][0]["backend"] == "chatgpt"
    assert stats["backends"][0]["answered"] is True


def test_get_hub_sessions_returns_sessions() -> None:
    response = _app(_FakeHubClient()).handle_request(
        method="GET",
        path="/v1/hub/sessions",
        body=b"",
        request_headers={"X-Correlation-Id": "req-hub-sessions"},
    )

    body = _json_body(response.body)
    assert response.status_code == HTTPStatus.OK
    sessions = body["sessions"]
    assert isinstance(sessions, list)
    assert sessions[0]["session_id"] == "s-1"


def test_post_hub_sessions_acquires_session() -> None:
    response = _app(_FakeHubClient()).handle_request(
        method="POST",
        path="/v1/hub/sessions",
        body=json.dumps(
            {
                "owner": "main",
                "description": "Main session",
                "llms": ["chatgpt"],
                "op_id": "op-acquire",
            },
        ).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-acquire"},
    )

    body = _json_body(response.body)
    assert response.status_code == HTTPStatus.CREATED
    assert body["op_id"] == "op-acquire"
    assert body["lease"] == {
        "session_id": "s-1",
        "token": "tok",
        "llms": ["chatgpt"],
        "slots": {"chatgpt": 0},
    }


def test_post_hub_messages_sends_message() -> None:
    response = _app(_FakeHubClient()).handle_request(
        method="POST",
        path="/v1/hub/sessions/s-1/messages",
        body=json.dumps(
            {
                "token": "tok",
                "message": "Hello",
                "op_id": "op-send",
            },
        ).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-send"},
    )

    body = _json_body(response.body)
    assert response.status_code == HTTPStatus.OK
    assert body["op_id"] == "op-send"
    messages = body["messages"]
    assert isinstance(messages, dict)
    chatgpt_msg = messages["chatgpt"]
    assert isinstance(chatgpt_msg, dict) and chatgpt_msg["text"] == "Hello"


def test_post_hub_release_releases_session() -> None:
    client = _FakeHubClient()
    response = _app(client).handle_request(
        method="POST",
        path="/v1/hub/sessions/s-1/release",
        body=json.dumps({"token": "tok", "op_id": "op-release"}).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-release"},
    )

    assert response.status_code == HTTPStatus.OK
    assert client.released == [("s-1", "tok")]


def test_hub_unavailable_returns_503() -> None:
    client = _FakeHubClient()
    client.unavailable = True

    response = _app(client).handle_request(
        method="GET",
        path="/v1/hub/status",
        body=b"",
        request_headers={"X-Correlation-Id": "req-down"},
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_get_hub_events_returns_sse_stream() -> None:
    response = _app(_FakeHubClient()).handle_request(
        method="GET",
        path="/v1/events/hub?topics=backend_status",
        body=b"",
        request_headers={"X-Correlation-Id": "req-hub-events"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.stream is not None
    payload = next(iter(response.stream)).decode("utf-8")
    assert "event: backend_status" in payload
    assert "event: sessions" not in payload
