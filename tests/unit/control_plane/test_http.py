from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path, PurePath

from agentkit.control_plane.http import ControlPlaneApplication, serve_control_plane
from agentkit.control_plane.models import (
    ControlPlaneMutationResult,
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
    TelemetryEventAccepted,
)
from agentkit.story.models import StoryDetail, StoryListResponse, StorySummary
from agentkit.story_context_manager.sizing import StorySize
from agentkit.story_context_manager.types import StoryMode, StoryType


def _runtime_result() -> ControlPlaneMutationResult:
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    return ControlPlaneMutationResult(
        status="committed",
        op_id="op-http-001",
        operation_kind="phase_start",
        run_id="run-100",
        phase="setup",
        edge_bundle=EdgeBundle(
            current=EdgePointer(
                project_key="tenant-a",
                export_version="edge-001",
                operating_mode="story_execution",
                bundle_dir="_temp/governance/bundles/edge-001",
                sync_after=now,
                freshness_class="mutation",
                generated_at=now,
            ),
            session=SessionRunBindingView(
                session_id="sess-001",
                project_key="tenant-a",
                story_id="AG3-100",
                run_id="run-100",
                principal_type="orchestrator",
                worktree_roots=["T:/worktrees/ag3-100"],
                binding_version="bind-001",
                operating_mode="story_execution",
            ),
            lock=StoryExecutionLockView(
                project_key="tenant-a",
                story_id="AG3-100",
                run_id="run-100",
                lock_type="story_execution",
                status="ACTIVE",
                worktree_roots=["T:/worktrees/ag3-100"],
                binding_version="bind-001",
                activated_at=now,
                updated_at=now,
            ),
        ),
    )


class _FakeTelemetryService:
    def __init__(self) -> None:
        self.requests: list[object] = []
        self.error: Exception | None = None

    def ingest_event(self, request: object) -> TelemetryEventAccepted:
        if self.error is not None:
            raise self.error
        self.requests.append(request)
        return TelemetryEventAccepted(event_id="evt-http-001")


class _FakeRuntimeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.error: Exception | None = None

    def start_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: object,
    ) -> ControlPlaneMutationResult:
        if self.error is not None:
            raise self.error
        self.calls.append((f"start:{run_id}", phase))
        return _runtime_result()

    def complete_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: object,
    ) -> ControlPlaneMutationResult:
        if self.error is not None:
            raise self.error
        self.calls.append((f"complete:{run_id}", phase))
        return _runtime_result().model_copy(
            update={"operation_kind": "phase_complete"},
        )

    def fail_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: object,
    ) -> ControlPlaneMutationResult:
        if self.error is not None:
            raise self.error
        self.calls.append((f"fail:{run_id}", phase))
        return _runtime_result().model_copy(update={"operation_kind": "phase_fail"})

    def complete_closure(
        self,
        *,
        run_id: str,
        request: object,
    ) -> ControlPlaneMutationResult:
        if self.error is not None:
            raise self.error
        self.calls.append((f"closure:{run_id}", None))
        return _runtime_result().model_copy(
            update={"operation_kind": "closure_complete"},
        )

    def sync_project_edge(self, request: object) -> ControlPlaneMutationResult:
        if self.error is not None:
            raise self.error
        self.calls.append(("sync", None))
        return _runtime_result().model_copy(
            update={"status": "synced", "operation_kind": "project_edge_sync"},
        )

    def get_operation(self, op_id: str) -> ControlPlaneMutationResult | None:
        if self.error is not None:
            raise self.error
        if op_id == "missing":
            return None
        self.calls.append((f"get:{op_id}", None))
        return _runtime_result().model_copy(update={"status": "replayed"})


class _FakeStoryService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.error: Exception | None = None

    def list_stories(self, project_key: str) -> StoryListResponse:
        if self.error is not None:
            raise self.error
        self.calls.append((project_key, None))
        return StoryListResponse(
            project_key=project_key,
            stories=[
                StorySummary(
                    project_key=project_key,
                    story_id="AG3-100",
                    title="Implement control plane",
                    story_type=StoryType.IMPLEMENTATION,
                    execution_route=StoryMode.EXECUTION,
                    story_size=StorySize.MEDIUM,
                    lifecycle_status="active",
                    active_phase="implementation",
                    phase_status="in_progress",
                ),
            ],
        )

    def get_story(self, project_key: str, story_id: str) -> StoryDetail | None:
        if self.error is not None:
            raise self.error
        if story_id == "missing":
            return None
        self.calls.append((project_key, story_id))
        return StoryDetail(
            project_key=project_key,
            story_id=story_id,
            title="Implement control plane",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            story_size=StorySize.MEDIUM,
            lifecycle_status="active",
            active_phase="implementation",
            phase_status="in_progress",
            labels=["size:medium"],
            participating_repos=["app"],
        )


def test_post_telemetry_event_returns_created() -> None:
    service = _FakeTelemetryService()
    app = ControlPlaneApplication(
        telemetry_service=service,
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
    )

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


def test_post_phase_start_returns_created() -> None:
    runtime = _FakeRuntimeService()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=runtime,
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(
        method="POST",
        path="/v1/story-runs/run-100/phases/setup/start",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "principal_type": "orchestrator",
                "worktree_roots": ["T:/worktrees/ag3-100"],
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.CREATED
    body = json.loads(response.body)
    assert body["operation_kind"] == "phase_start"
    assert runtime.calls == [("start:run-100", "setup")]


def test_post_project_edge_sync_returns_ok() -> None:
    runtime = _FakeRuntimeService()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=runtime,
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(
        method="POST",
        path="/v1/project-edge/sync",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "session_id": "sess-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.OK
    assert json.loads(response.body)["operation_kind"] == "project_edge_sync"
    assert runtime.calls == [("sync", None)]


def test_post_phase_complete_and_fail_route_to_runtime() -> None:
    runtime = _FakeRuntimeService()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=runtime,
        story_service=_FakeStoryService(),
    )
    payload = json.dumps(
        {
            "project_key": "tenant-a",
            "story_id": "AG3-100",
            "session_id": "sess-001",
            "principal_type": "orchestrator",
            "worktree_roots": ["T:/worktrees/ag3-100"],
        },
    ).encode("utf-8")

    complete_response = app.handle_request(
        method="POST",
        path="/v1/story-runs/run-100/phases/setup/complete",
        body=payload,
    )
    fail_response = app.handle_request(
        method="POST",
        path="/v1/story-runs/run-100/phases/setup/fail",
        body=payload,
    )

    assert complete_response.status_code == HTTPStatus.CREATED
    assert fail_response.status_code == HTTPStatus.CREATED
    assert runtime.calls == [
        ("complete:run-100", "setup"),
        ("fail:run-100", "setup"),
    ]


def test_post_closure_complete_returns_created() -> None:
    runtime = _FakeRuntimeService()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=runtime,
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(
        method="POST",
        path="/v1/story-runs/run-100/closure/complete",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.CREATED
    assert json.loads(response.body)["operation_kind"] == "closure_complete"
    assert runtime.calls == [("closure:run-100", None)]


def test_get_operation_returns_ok() -> None:
    runtime = _FakeRuntimeService()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=runtime,
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(
        method="GET",
        path="/v1/project-edge/operations/op-http-001",
        body=b"",
    )

    assert response.status_code == HTTPStatus.OK
    assert json.loads(response.body)["status"] == "replayed"
    assert runtime.calls == [("get:op-http-001", None)]


def test_get_missing_operation_returns_not_found() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(
        method="GET",
        path="/v1/project-edge/operations/missing",
        body=b"",
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert json.loads(response.body) == {"error": "Operation not found"}


def test_healthz_returns_ok() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(method="GET", path="/healthz", body=b"")

    assert response.status_code == HTTPStatus.OK
    assert json.loads(response.body) == {"status": "ok"}


def test_healthz_wrong_method_returns_allow_header() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(method="POST", path="/healthz", body=b"")

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert response.headers == (("Allow", "GET"),)


def test_unknown_path_returns_not_found() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(method="GET", path="/missing", body=b"")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert json.loads(response.body) == {"error": "Not found"}


def test_invalid_json_returns_bad_request() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(
        method="POST",
        path="/v1/telemetry/events",
        body=b"{invalid",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert json.loads(response.body) == {
        "error": "Request body must be valid JSON",
    }


def test_get_stories_returns_project_scoped_list() -> None:
    story_service = _FakeStoryService()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=story_service,
    )

    response = app.handle_request(
        method="GET",
        path="/v1/stories?project_key=tenant-a",
        body=b"",
    )

    assert response.status_code == HTTPStatus.OK
    body = json.loads(response.body)
    assert body["project_key"] == "tenant-a"
    assert body["stories"][0]["story_id"] == "AG3-100"
    assert story_service.calls == [("tenant-a", None)]


def test_get_story_returns_detail() -> None:
    story_service = _FakeStoryService()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=story_service,
    )

    response = app.handle_request(
        method="GET",
        path="/v1/stories/AG3-100?project_key=tenant-a",
        body=b"",
    )

    assert response.status_code == HTTPStatus.OK
    body = json.loads(response.body)
    assert body["story_id"] == "AG3-100"
    assert body["labels"] == ["size:medium"]
    assert story_service.calls == [("tenant-a", "AG3-100")]


def test_get_story_requires_project_key() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(
        method="GET",
        path="/v1/stories/AG3-100",
        body=b"",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert json.loads(response.body) == {
        "error": "Missing required query parameter: project_key",
    }


def test_get_missing_story_returns_not_found() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(
        method="GET",
        path="/v1/stories/missing?project_key=tenant-a",
        body=b"",
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert json.loads(response.body) == {"error": "Story not found"}


def test_invalid_payload_returns_bad_request() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
    )

    response = app.handle_request(
        method="POST",
        path="/v1/telemetry/events",
        body=json.dumps({"story_id": "AG3-100"}).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(response.body)
    assert body["error"] == "Invalid telemetry event payload"
    assert isinstance(body["detail"], list)


def test_invalid_phase_payload_returns_bad_request() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
    )

    response = app.handle_request(
        method="POST",
        path="/v1/story-runs/run-100/phases/setup/start",
        body=json.dumps({"story_id": "AG3-100"}).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert json.loads(response.body)["error"] == "Invalid phase mutation payload"


def test_invalid_closure_payload_returns_bad_request() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
    )

    response = app.handle_request(
        method="POST",
        path="/v1/story-runs/run-100/closure/complete",
        body=json.dumps({"story_id": "AG3-100"}).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert json.loads(response.body)["error"] == "Invalid closure payload"


def test_invalid_project_edge_sync_payload_returns_bad_request() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
    )

    response = app.handle_request(
        method="POST",
        path="/v1/project-edge/sync",
        body=json.dumps({"project_key": "tenant-a"}).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert json.loads(response.body)["error"] == "Invalid project-edge sync payload"


def test_runtime_unavailable_returns_service_unavailable() -> None:
    runtime = _FakeRuntimeService()
    runtime.error = RuntimeError("postgres unavailable")
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=runtime,
    )

    response = app.handle_request(
        method="POST",
        path="/v1/project-edge/sync",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "session_id": "sess-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert json.loads(response.body) == {"error": "postgres unavailable"}


def test_phase_runtime_unavailable_returns_service_unavailable() -> None:
    runtime = _FakeRuntimeService()
    runtime.error = RuntimeError("phase backend unavailable")
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=runtime,
    )

    response = app.handle_request(
        method="POST",
        path="/v1/story-runs/run-100/phases/setup/start",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "principal_type": "orchestrator",
                "worktree_roots": ["T:/worktrees/ag3-100"],
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert json.loads(response.body) == {"error": "phase backend unavailable"}


def test_serve_control_plane_runs_and_closes_server(monkeypatch) -> None:
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

    monkeypatch.setattr("agentkit.control_plane.http.ThreadingHTTPSServer", _FakeServer)

    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
    )
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
