from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path, PurePath

from agentkit.control_plane.http import ControlPlaneApplication, serve_control_plane
from agentkit.control_plane.models import TelemetryEventAccepted


class _FakeTelemetryService:
    def __init__(self) -> None:
        self.requests: list[object] = []
        self.error: Exception | None = None

    def ingest_event(self, request: object) -> TelemetryEventAccepted:
        if self.error is not None:
            raise self.error
        self.requests.append(request)
        return TelemetryEventAccepted(event_id="evt-http-001")


def test_post_telemetry_event_returns_created() -> None:
    service = _FakeTelemetryService()
    app = ControlPlaneApplication(telemetry_service=service)

    response = app.handle_request(
        method="POST",
        path="/v1/telemetry/events",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "run_id": "run-100",
                "event_type": "agent_start",
                "occurred_at": "2026-04-20T10:00:00+00:00",
                "source_component": "control-plane",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.CREATED
    assert json.loads(response.body) == {
        "event_id": "evt-http-001",
        "status": "accepted",
    }
    assert len(service.requests) == 1


def test_healthz_returns_ok() -> None:
    app = ControlPlaneApplication(telemetry_service=_FakeTelemetryService())

    response = app.handle_request(method="GET", path="/healthz", body=b"")

    assert response.status_code == HTTPStatus.OK
    assert json.loads(response.body) == {"status": "ok"}


def test_healthz_wrong_method_returns_allow_header() -> None:
    app = ControlPlaneApplication(telemetry_service=_FakeTelemetryService())

    response = app.handle_request(method="POST", path="/healthz", body=b"")

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert response.headers == (("Allow", "GET"),)


def test_unknown_path_returns_not_found() -> None:
    app = ControlPlaneApplication(telemetry_service=_FakeTelemetryService())

    response = app.handle_request(method="GET", path="/missing", body=b"")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert json.loads(response.body) == {"error": "Not found"}


def test_wrong_method_returns_allow_header() -> None:
    app = ControlPlaneApplication(telemetry_service=_FakeTelemetryService())

    response = app.handle_request(
        method="GET",
        path="/v1/telemetry/events",
        body=b"",
    )

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert response.headers == (("Allow", "POST"),)


def test_invalid_json_returns_bad_request() -> None:
    app = ControlPlaneApplication(telemetry_service=_FakeTelemetryService())

    response = app.handle_request(
        method="POST",
        path="/v1/telemetry/events",
        body=b"{invalid",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert json.loads(response.body) == {
        "error": "Request body must be valid JSON",
    }


def test_invalid_payload_returns_bad_request() -> None:
    app = ControlPlaneApplication(telemetry_service=_FakeTelemetryService())

    response = app.handle_request(
        method="POST",
        path="/v1/telemetry/events",
        body=json.dumps({"story_id": "AG3-100"}).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(response.body)
    assert body["error"] == "Invalid telemetry event payload"
    assert isinstance(body["detail"], list)


def test_backend_unavailable_returns_service_unavailable() -> None:
    service = _FakeTelemetryService()
    service.error = RuntimeError("postgres unavailable")
    app = ControlPlaneApplication(telemetry_service=service)

    response = app.handle_request(
        method="POST",
        path="/v1/telemetry/events",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "run_id": "run-100",
                "event_type": "agent_start",
                "occurred_at": "2026-04-20T10:00:00+00:00",
                "source_component": "control-plane",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert json.loads(response.body) == {"error": "postgres unavailable"}


def test_serve_control_plane_runs_and_closes_server(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeServer:
        def __init__(
            self,
            address: tuple[str, int],
            handler_cls: object,
            *,
            certfile: str,
            keyfile: str | None,
        ) -> None:
            captured["address"] = address
            captured["handler_cls"] = handler_cls
            captured["certfile"] = certfile
            captured["keyfile"] = keyfile

        def serve_forever(self) -> None:
            captured["served"] = True

        def server_close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(
        "agentkit.control_plane.http.ThreadingHTTPSServer",
        _FakeServer,
    )

    app = ControlPlaneApplication(telemetry_service=_FakeTelemetryService())
    serve_control_plane(
        host="127.0.0.1",
        port=9911,
        certfile=Path("tls/control-plane.pem"),
        keyfile=Path("tls/control-plane.key"),
        app=app,
    )

    assert captured["address"] == ("127.0.0.1", 9911)
    assert captured["certfile"] == str(PurePath("tls/control-plane.pem"))
    assert captured["keyfile"] == str(PurePath("tls/control-plane.key"))
    assert captured["served"] is True
    assert captured["closed"] is True
