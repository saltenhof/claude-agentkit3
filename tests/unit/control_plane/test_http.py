from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, cast

from tests.story_read_port_stub import StubStoryReadPort

from agentkit.backend.control_plane.http import (
    ControlPlaneApplication,
    ControlPlaneApplicationRoutes,
    HttpResponse,
    serve_control_plane,
)
from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    EdgeBundle,
    EdgePointer,
    PhaseDispatchResult,
    SessionRunBindingView,
    StoryExecutionLockView,
    TelemetryEventAccepted,
)
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.control_plane.telemetry import ControlPlaneTelemetryService
from agentkit.backend.kpi_analytics.dashboard.models import (
    BoardColumn,
    DashboardBoardResponse,
    DashboardStoryMetricsItem,
    DashboardStoryMetricsResponse,
    DashboardStorySummary,
)
from agentkit.backend.kpi_analytics.dashboard.service import DashboardService
from agentkit.backend.story.models import StoryDetail, StoryListResponse, StorySummary
from agentkit.backend.story.service import StoryService
from agentkit.backend.story_context_manager.http.routes import (
    StoryContextRoutes,
    StoryRouteResponse,
)
from agentkit.backend.story_context_manager.sizing import StorySize
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    import pytest

    from agentkit.backend.control_plane_http.third_party_validation_routes import (
        ThirdPartyValidationRoutes,
    )


class _AbstainingThirdPartyValidationRoutes:
    """Keep legacy-operation unit tests isolated from productive persistence."""

    def handle_get(self, route_path: str, correlation_id: str) -> None:
        del route_path, correlation_id


def _legacy_operation_routes() -> ControlPlaneApplicationRoutes:
    return ControlPlaneApplicationRoutes(
        third_party_validation_routes=cast(
            "ThirdPartyValidationRoutes", _AbstainingThirdPartyValidationRoutes()
        )
    )


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


class _FakeTelemetryService(ControlPlaneTelemetryService):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[object] = []
        self.error: Exception | None = None

    def ingest_event(self, request: object) -> TelemetryEventAccepted:
        if self.error is not None:
            raise self.error
        self.requests.append(request)
        return TelemetryEventAccepted(event_id="evt-http-001")


class _FakeRuntimeService(ControlPlaneRuntimeService):
    def __init__(self) -> None:
        super().__init__()
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


class _FakeStoryService(StoryService):
    def __init__(self) -> None:
        super().__init__(repository=StubStoryReadPort())
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
                    story_size=StorySize.M,
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
            story_size=StorySize.M,
            lifecycle_status="active",
            active_phase="implementation",
            phase_status="in_progress",
            labels=["size:medium"],
            participating_repos=["app"],
        )


class _FakeStoryContextRoutes(StoryContextRoutes):
    """Stub StoryContextRoutes for control-plane routing tests.

    Avoids real service/repo construction; only verifies routing decisions.
    """

    def __init__(self) -> None:
        # Intentionally skip StoryContextRoutes.__init__ to avoid DB access.
        self.get_calls: list[tuple[str, str]] = []
        self.patch_calls: list[tuple[str, object]] = []
        self.put_calls: list[tuple[str, str, object]] = []

    def handle_get(
        self,
        route_path: str,
        correlation_id: str,
        query: dict[str, list[str]] | None = None,
    ) -> StoryRouteResponse | None:
        query = query or {}
        # Only claim ownership of the /v1/stories collection and detail paths.
        if route_path == "/v1/stories":
            self.get_calls.append((route_path, correlation_id))
            project_key_values = query.get("project_key", [])
            if not project_key_values:
                return StoryRouteResponse(
                    status_code=400,
                    body=json.dumps({
                        "error_code": "missing_project_key",
                        "error": "Missing required query parameter: project_key",
                        "correlation_id": correlation_id,
                    }).encode(),
                    headers=(("X-Correlation-Id", correlation_id),),
                )
            project_key = project_key_values[0]
            return StoryRouteResponse(
                status_code=200,
                body=json.dumps({
                    "project_key": project_key,
                    "stories": [{"story_id": "AG3-100"}],
                }).encode(),
                headers=(("X-Correlation-Id", correlation_id),),
            )
        if route_path.startswith("/v1/stories/"):
            story_id = route_path[len("/v1/stories/"):]
            if "/" not in story_id:
                # detail path
                self.get_calls.append((route_path, correlation_id))
                if story_id == "missing":
                    return StoryRouteResponse(
                        status_code=404,
                        body=json.dumps({
                            "error_code": "story_not_found",
                            "error": "Story not found",
                            "correlation_id": correlation_id,
                        }).encode(),
                        headers=(("X-Correlation-Id", correlation_id),),
                    )
                return StoryRouteResponse(
                    status_code=200,
                    body=json.dumps({
                        "summary": {
                            "story_id": story_id,
                            "project_key": "tenant-a",
                            "title": "Implement control plane",
                        },
                        "spec": None,
                    }).encode(),
                    headers=(("X-Correlation-Id", correlation_id),),
                )
        return None

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> StoryRouteResponse | None:
        return None

    def handle_patch(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> StoryRouteResponse | None:
        if route_path.startswith("/v1/stories/"):
            self.patch_calls.append((route_path, payload))
            return StoryRouteResponse(
                status_code=200,
                body=json.dumps({"story_id": "AG3-100"}).encode(),
                headers=(("X-Correlation-Id", correlation_id),),
            )
        return None

    def handle_put(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> StoryRouteResponse | None:
        if "/fields/" in route_path and route_path.startswith("/v1/stories/"):
            parts = route_path.split("/fields/")
            self.put_calls.append((route_path, parts[-1], payload))
            return StoryRouteResponse(
                status_code=200,
                body=json.dumps({"story_id": "AG3-100"}).encode(),
                headers=(("X-Correlation-Id", correlation_id),),
            )
        return None


class _FakeDashboardService(DashboardService):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str]] = []
        self.error: Exception | None = None

    def get_board(self, project_key: str) -> DashboardBoardResponse:
        if self.error is not None:
            raise self.error
        self.calls.append(("board", project_key))
        return DashboardBoardResponse(
            project_key=project_key,
            columns=[
                BoardColumn(
                    status="active",
                    stories=[
                        DashboardStorySummary(
                            story_id="AG3-100",
                            title="Implement control plane",
                            story_type=str(StoryType.IMPLEMENTATION),
                            execution_route=str(StoryMode.EXECUTION),
                            story_size=StorySize.M,
                            lifecycle_status="active",
                            active_phase="implementation",
                            phase_status="in_progress",
                        ),
                    ],
                ),
            ],
        )

    def get_story_metrics(self, project_key: str, period: object = None) -> DashboardStoryMetricsResponse:  # noqa: ARG002
        if self.error is not None:
            raise self.error
        self.calls.append(("metrics", project_key))
        return DashboardStoryMetricsResponse(
            project_key=project_key,
            stories=[
                DashboardStoryMetricsItem(
                    story_id="AG3-101",
                    title="Stabilize telemetry",
                    story_type=str(StoryType.IMPLEMENTATION),
                    story_size=StorySize.S,
                    final_status="DONE",
                    processing_time_min=12.5,
                    qa_rounds=2,
                    increments=1,
                    completed_at=datetime(2026, 4, 22, 11, 0, tzinfo=UTC),
                ),
            ],
        )


class _NoopTenantScopeMiddleware:
    """Passthrough tenant-scope stub: all project_keys pass (no real DB access).

    Used by tests that exercise paths which now require project_key in the URL
    (AG3-090) but do not test tenant-scope validation itself.
    """

    def validate(self, *, method: str, route_path: str, correlation_id: str) -> None:
        return None


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
    assert _json_body(response) == {
        "event_id": "evt-http-001",
        "status": "accepted",
    }
    assert _response_header(response, "X-Correlation-Id").startswith("req-")
    assert len(service.requests) == 1


def test_post_phase_start_returns_created() -> None:
    runtime = _FakeRuntimeService()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=runtime,
        story_service=_FakeStoryService(),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/start",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "principal_type": "orchestrator",
                "worktree_roots": ["T:/worktrees/ag3-100"],
                "op_id": "op-phase-start-created-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.CREATED
    body = json.loads(response.body)
    assert body["operation_kind"] == "phase_start"
    assert runtime.calls == [("start:run-100", "setup")]


class _RejectingRuntimeService(ControlPlaneRuntimeService):
    """Runtime stub whose ``start_phase`` returns a fail-closed rejection."""

    def start_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: object,
    ) -> ControlPlaneMutationResult:
        del request
        return ControlPlaneMutationResult(
            status="rejected",
            op_id="op-rejected-http",
            operation_kind="phase_start",
            run_id=run_id,
            phase=phase,
            edge_bundle=None,
            phase_dispatch=PhaseDispatchResult(
                phase=phase,
                status="rejected",
                reaction="rejected",
                dispatched=False,
                rejection_reason="StoryStatus is not Approved (Tor 1).",
            ),
        )


def test_post_phase_start_rejection_returns_conflict() -> None:
    """AG3-054 (FK-20 §20.8.2): a fail-closed REJECTED start is 409, not 201.

    A rejection materialized no run state; it must never be reported as a
    201 CREATED success (which would imply the run was admitted). The HTTP
    layer maps it to 409 Conflict and serializes the (``edge_bundle=None``)
    result without crashing; the rejection detail rides on ``phase_dispatch``.
    """
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_RejectingRuntimeService(),
        story_service=_FakeStoryService(),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/start",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "principal_type": "orchestrator",
                "worktree_roots": ["T:/worktrees/ag3-100"],
                "op_id": "op-phase-start-rejected-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.CONFLICT
    body = json.loads(response.body)
    assert body["status"] == "rejected"
    assert body["edge_bundle"] is None
    assert body["phase_dispatch"]["dispatched"] is False
    assert body["phase_dispatch"]["status"] == "rejected"


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
                "op_id": "op-sync-ok-001",
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
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )
    payload = json.dumps(
        {
            "project_key": "tenant-a",
            "story_id": "AG3-100",
            "session_id": "sess-001",
            "principal_type": "orchestrator",
            "worktree_roots": ["T:/worktrees/ag3-100"],
            "op_id": "op-complete-and-fail-001",
        },
    ).encode("utf-8")

    complete_response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/complete",
        body=payload,
    )
    fail_response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/fail",
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
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/closure/complete",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "op_id": "op-closure-created-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.CREATED
    assert json.loads(response.body)["operation_kind"] == "closure_complete"
    assert runtime.calls == [("closure:run-100", None)]


def test_get_operation_returns_ok() -> None:
    runtime = _FakeRuntimeService()
    app = ControlPlaneApplication(
        routes=_legacy_operation_routes(),
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
        routes=_legacy_operation_routes(),
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
    _assert_error(
        response,
        error_code="operation_not_found",
        message="Operation not found",
    )


def test_healthz_returns_ok() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(method="GET", path="/healthz", body=b"")

    assert response.status_code == HTTPStatus.OK
    assert _json_body(response) == {"status": "ok"}
    assert _response_header(response, "X-Correlation-Id").startswith("req-")


def test_healthz_wrong_method_returns_allow_header() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(method="POST", path="/healthz", body=b"")

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert ("Allow", "GET") in response.headers
    _assert_error(
        response,
        error_code="method_not_allowed",
        message="Method not allowed",
    )


def test_unknown_path_returns_not_found() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(method="GET", path="/missing", body=b"")

    assert response.status_code == HTTPStatus.NOT_FOUND
    _assert_error(response, error_code="not_found", message="Not found")


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
    _assert_error(
        response,
        error_code="invalid_json",
        message="Request body must be valid JSON",
    )


def test_get_stories_legacy_path_returns_404() -> None:
    """GET /v1/stories (legacy bare path) is no longer exposed; must return 404 (AC2)."""
    fake_routes = _FakeStoryContextRoutes()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        routes=ControlPlaneApplicationRoutes(story_routes=fake_routes),
    )

    response = app.handle_request(
        method="GET",
        path="/v1/stories?project_key=tenant-a",
        body=b"",
    )

    # Legacy surface is removed; all story access via /v1/projects/{key}/stories (AC2).
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert json.loads(response.body)["error_code"] == "not_found"
    # story_routes must NOT have been called (no implicit bypass)
    assert fake_routes.get_calls == []


def test_get_story_legacy_detail_path_returns_404() -> None:
    """GET /v1/stories/{id} (legacy bare path) is no longer exposed; must return 404 (AC2)."""
    fake_routes = _FakeStoryContextRoutes()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        routes=ControlPlaneApplicationRoutes(story_routes=fake_routes),
    )

    response = app.handle_request(
        method="GET",
        path="/v1/stories/AG3-100",
        body=b"",
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert json.loads(response.body)["error_code"] == "not_found"
    assert fake_routes.get_calls == []


def test_get_stories_legacy_bare_path_returns_404() -> None:
    """GET /v1/stories (no project_key) is not routed to story_routes any more (AC2)."""
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        routes=ControlPlaneApplicationRoutes(story_routes=_FakeStoryContextRoutes()),
    )

    response = app.handle_request(
        method="GET",
        path="/v1/stories",
        body=b"",
    )

    # Not a project-scoped path → 404, NOT the old 400 missing_project_key.
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert json.loads(response.body)["error_code"] == "not_found"


def test_get_missing_story_legacy_path_returns_404() -> None:
    """GET /v1/stories/missing via legacy path is not routed; generic 404 (AC2)."""
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        routes=ControlPlaneApplicationRoutes(story_routes=_FakeStoryContextRoutes()),
    )

    response = app.handle_request(
        method="GET",
        path="/v1/stories/missing",
        body=b"",
    )

    # error_code is "not_found" (route missing), NOT "story_not_found" (service miss).
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert json.loads(response.body)["error_code"] == "not_found"


def test_patch_story_legacy_path_returns_404() -> None:
    """PATCH /v1/stories/{id} (legacy bare path) no longer resolves; 404 (AC2/AC3)."""
    fake_routes = _FakeStoryContextRoutes()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        routes=ControlPlaneApplicationRoutes(story_routes=fake_routes),
    )

    response = app.handle_request(
        method="PATCH",
        path="/v1/stories/AG3-100",
        body=json.dumps({"op_id": "op-patch-1", "title": "New title"}).encode(),
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert json.loads(response.body)["error_code"] == "not_found"
    # story_routes.handle_patch must NOT have been called via the legacy path
    assert fake_routes.patch_calls == []


def test_put_story_field_legacy_path_returns_404() -> None:
    """PUT /v1/stories/{id}/fields/{key} (legacy bare path) no longer resolves; 404 (AC2/AC3)."""
    fake_routes = _FakeStoryContextRoutes()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        routes=ControlPlaneApplicationRoutes(story_routes=fake_routes),
    )

    response = app.handle_request(
        method="PUT",
        path="/v1/stories/AG3-100/fields/title",
        body=json.dumps({"op_id": "op-put-1", "value": "New title"}).encode(),
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert json.loads(response.body)["error_code"] == "not_found"
    assert fake_routes.put_calls == []


def test_get_dashboard_board_returns_project_scoped_columns() -> None:
    dashboard_service = _FakeDashboardService()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
        dashboard_service=dashboard_service,
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="GET",
        path="/v1/projects/tenant-a/dashboard/board",
        body=b"",
    )

    assert response.status_code == HTTPStatus.OK
    body = json.loads(response.body)
    assert body["project_key"] == "tenant-a"
    assert body["columns"][0]["status"] == "active"
    assert dashboard_service.calls == [("board", "tenant-a")]


def test_get_dashboard_story_metrics_returns_project_scoped_metrics() -> None:
    dashboard_service = _FakeDashboardService()
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
        dashboard_service=dashboard_service,
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="GET",
        path="/v1/projects/tenant-a/dashboard/story-metrics",
        body=b"",
    )

    assert response.status_code == HTTPStatus.OK
    body = json.loads(response.body)
    assert body["project_key"] == "tenant-a"
    assert body["stories"][0]["story_id"] == "AG3-101"
    assert dashboard_service.calls == [("metrics", "tenant-a")]


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
    body = _assert_error(
        response,
        error_code="invalid_telemetry_event_payload",
        message="Invalid telemetry event payload",
    )
    assert isinstance(body["detail"], list)


def test_invalid_phase_payload_returns_bad_request() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    # op_id is present (valid) so this exercises the ordinary 400 payload-shape
    # path, distinct from the AG3-140 op_id-specific 422 (see
    # test_missing_op_id_phase_payload_returns_422 below).
    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/start",
        body=json.dumps({"story_id": "AG3-100", "op_id": "op-phase-bad-1"}).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    _assert_error(
        response,
        error_code="invalid_phase_mutation_payload",
        message="Invalid phase mutation payload",
    )


def test_missing_op_id_phase_payload_returns_422() -> None:
    """AG3-140 (FK-91 §91.1a Rule 5, AC1): a phase mutation without op_id is 422."""
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/start",
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

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    _assert_error(
        response,
        error_code="invalid_phase_mutation_payload",
        message="Invalid phase mutation payload",
    )


def test_invalid_closure_payload_returns_bad_request() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    # op_id is present (valid) so this exercises the ordinary 400 payload-shape
    # path, distinct from the AG3-140 op_id-specific 422.
    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/closure/complete",
        body=json.dumps({"story_id": "AG3-100", "op_id": "op-closure-bad-1"}).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    _assert_error(
        response,
        error_code="invalid_closure_payload",
        message="Invalid closure payload",
    )


def test_missing_op_id_closure_payload_returns_422() -> None:
    """AG3-140 (FK-91 §91.1a Rule 5, AC1): a closure completion without op_id is 422."""
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/closure/complete",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    _assert_error(
        response,
        error_code="invalid_closure_payload",
        message="Invalid closure payload",
    )


def test_missing_op_id_guard_counter_payload_returns_422() -> None:
    """AG3-140 (Codex r7 PATH 4 P1; FK-91 §91.1a Rule 5, AC1): a guard-counter
    mutation without op_id is 422.

    ``POST /v1/governance/guard-counters`` is a mutating HTTP route whose ``op_id``
    is a required client-supplied idempotency key (``GuardCounterMutationRequest.
    op_id = Field(min_length=1)``, no server default). A missing op_id fails closed
    with an op_id-specific 422, distinct from an ordinary 400 payload-shape defect.
    Validation precedes any guard-counter service call, so this holds at the wire.
    """
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    # A body valid in every respect EXCEPT the missing op_id (``housekeeping`` needs
    # no record-scope fields), so the only validation failure is the op_id -> 422.
    response = app.handle_request(
        method="POST",
        path="/v1/governance/guard-counters",
        body=json.dumps(
            {
                "operation": "housekeeping",
                "occurred_at": "2026-07-02T11:00:00+00:00",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    _assert_error(
        response,
        error_code="invalid_guard_counter_payload",
        message="Invalid guard-counter mutation payload",
    )


def test_invalid_project_edge_sync_payload_returns_bad_request() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
    )

    # op_id is present (valid) so this exercises the ordinary 400 payload-shape
    # path, distinct from the AG3-140 op_id-specific 422.
    response = app.handle_request(
        method="POST",
        path="/v1/project-edge/sync",
        body=json.dumps({"project_key": "tenant-a", "op_id": "op-sync-bad-1"}).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    _assert_error(
        response,
        error_code="invalid_project_edge_sync_payload",
        message="Invalid project-edge sync payload",
    )


def test_missing_op_id_project_edge_sync_payload_returns_422() -> None:
    """AG3-140 (FK-91 §91.1a Rule 5, AC1): a project-edge sync without op_id is 422."""
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
    )

    response = app.handle_request(
        method="POST",
        path="/v1/project-edge/sync",
        body=json.dumps({"project_key": "tenant-a", "session_id": "sess-001"}).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    _assert_error(
        response,
        error_code="invalid_project_edge_sync_payload",
        message="Invalid project-edge sync payload",
    )


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
                "op_id": "op-sync-unavailable-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    _assert_error(
        response,
        error_code="project_edge_sync_unavailable",
        message="postgres unavailable",
    )


def test_phase_runtime_unavailable_returns_service_unavailable() -> None:
    runtime = _FakeRuntimeService()
    runtime.error = RuntimeError("phase backend unavailable")
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=runtime,
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/start",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "principal_type": "orchestrator",
                "worktree_roots": ["T:/worktrees/ag3-100"],
                "op_id": "op-phase-unavailable-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    _assert_error(
        response,
        error_code="phase_mutation_unavailable",
        message="phase backend unavailable",
    )


# ---------------------------------------------------------------------------
# AG3-054 PART D (#4): a ConfigError (backend requirement) -> structured 503
# ---------------------------------------------------------------------------


_CONFIG_ERROR_MESSAGE = "The control-plane runtime requires the Postgres state backend"


def _config_error_app() -> ControlPlaneApplication:
    from agentkit.backend.exceptions import ConfigError

    runtime = _FakeRuntimeService()
    runtime.error = ConfigError(_CONFIG_ERROR_MESSAGE)
    return ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=runtime,
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )


def test_config_error_on_phase_start_returns_structured_503() -> None:
    """PART D (#4): a ConfigError from the Postgres gate -> 503, not an uncaught 500."""
    response = _config_error_app().handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/start",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "principal_type": "orchestrator",
                "worktree_roots": ["T:/worktrees/ag3-100"],
                "op_id": "op-config-error-start-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    _assert_error(
        response,
        error_code="phase_mutation_unavailable",
        message=_CONFIG_ERROR_MESSAGE,
    )


def test_config_error_on_phase_complete_returns_structured_503() -> None:
    response = _config_error_app().handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/complete",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "principal_type": "orchestrator",
                "worktree_roots": ["T:/worktrees/ag3-100"],
                "op_id": "op-config-error-complete-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    _assert_error(
        response,
        error_code="phase_mutation_unavailable",
        message=_CONFIG_ERROR_MESSAGE,
    )


def test_config_error_on_phase_fail_returns_structured_503() -> None:
    response = _config_error_app().handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/fail",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "principal_type": "orchestrator",
                "worktree_roots": ["T:/worktrees/ag3-100"],
                "op_id": "op-config-error-fail-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    _assert_error(
        response,
        error_code="phase_mutation_unavailable",
        message=_CONFIG_ERROR_MESSAGE,
    )


def test_config_error_on_closure_returns_structured_503() -> None:
    response = _config_error_app().handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/closure/complete",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "op_id": "op-config-error-closure-001",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    _assert_error(
        response,
        error_code="closure_unavailable",
        message=_CONFIG_ERROR_MESSAGE,
    )


def test_incoming_correlation_id_is_propagated() -> None:
    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
        story_service=_FakeStoryService(),
    )

    response = app.handle_request(
        method="GET",
        path="/healthz",
        body=b"",
        request_headers={"X-Correlation-Id": "corr-fixed-001"},
    )

    assert response.status_code == HTTPStatus.OK
    assert _response_header(response, "X-Correlation-Id") == "corr-fixed-001"


def test_serve_control_plane_runs_and_closes_server(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr("agentkit.backend.control_plane_http.app.ThreadingHTTPSServer", _FakeServer)

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
        # AG3-138: this transport-wiring test drives only server start/close; the
        # pre-serve startup hook (instance-identity + reconciliation) has its own
        # dedicated tests and needs a live control-plane backend, so inject a
        # no-op here (the productive listener always runs the real hook).
        startup_hook=lambda _app: None,
    )

    assert captured["address"] == ("127.0.0.1", 9911)
    assert captured["certfile"] == str(PurePath("tls/control-plane.pem"))
    assert captured["keyfile"] == str(PurePath("tls/control-plane.key"))
    assert captured["served"] is True
    assert captured["closed"] is True


def test_serve_control_plane_does_not_start_when_startup_hook_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9: a failing pre-serve startup hook prevents the server from starting.

    The pre-serve hook (instance-identity resolution + orphan reconciliation)
    runs BEFORE the socket is bound and BEFORE ``serve_forever()``. A fail-closed
    hook failure (e.g. :class:`StartupReconciliationError`) must propagate
    uncaught so the listener NEVER starts serving with an unclear claim
    inventory -- and the server object is never even constructed.
    """
    import pytest as _pytest

    from agentkit.backend.control_plane.startup_reconcile import (
        StartupReconciliationError,
    )

    constructed = {"built": False, "served": False}

    class _NeverServer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            constructed["built"] = True

        def serve_forever(self) -> None:  # pragma: no cover - must never run
            constructed["served"] = True

        def server_close(self) -> None:  # pragma: no cover - must never run
            pass

    monkeypatch.setattr(
        "agentkit.backend.control_plane_http.app.ThreadingHTTPSServer", _NeverServer
    )

    app = ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=_FakeRuntimeService(),
    )

    def _failing_hook(_app: ControlPlaneApplication) -> None:
        raise StartupReconciliationError("simulated reconcile failure (AC9)")

    with _pytest.raises(StartupReconciliationError):
        serve_control_plane(
            host="127.0.0.1",
            port=9912,
            certfile=Path("tls/control-plane.pem"),
            keyfile=None,
            app=app,
            startup_hook=_failing_hook,
        )

    # Fail-closed: the server was never built and never served.
    assert constructed["built"] is False
    assert constructed["served"] is False


def _json_body(response: HttpResponse) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(response.body))


def _response_header(response: HttpResponse, name: str) -> str:
    for key, value in response.headers:
        if key == name:
            return value
    raise AssertionError(f"Missing response header: {name}")


def _assert_error(
    response: HttpResponse,
    *,
    error_code: str,
    message: str,
) -> dict[str, object]:
    body = _json_body(response)
    assert body["error_code"] == error_code
    assert body["error"] == message
    assert isinstance(body["correlation_id"], str)
    assert body["correlation_id"] != ""
    assert _response_header(response, "X-Correlation-Id") == body["correlation_id"]
    return body


# ===========================================================================
# AG3-138: POST /v1/project-edge/operations/{op_id}/admin-abort (FK-91 §91.1a,
# FK-55 §55.5 ``admin_transition``). Deterministic, fail-closed HTTP contract:
# 404 unknown op / 409 not-abortable / 200 aborted|repair; plus the AC10
# mutation-lock rejection mapping to 409 at the phase-mutation route.
# ===========================================================================


def _abort_result(status: str) -> ControlPlaneMutationResult:
    return ControlPlaneMutationResult(
        status=status,  # type: ignore[arg-type]
        op_id="op-abort-1",
        operation_kind="phase_start",
        run_id="run-100",
        phase="implementation",
        edge_bundle=None,
        phase_dispatch=None,
        admin_note=f"admin_abort_inflight_operation: {status}",
    )


class _AbortRuntimeService(ControlPlaneRuntimeService):
    """A runtime stand-in whose admin-abort returns/raises a configured outcome."""

    def __init__(
        self,
        *,
        result: ControlPlaneMutationResult | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self._result = result
        self._error = error
        self.calls: list[tuple[str, object]] = []

    def admin_abort_inflight_operation(
        self, op_id: str, request: object
    ) -> ControlPlaneMutationResult:
        self.calls.append((op_id, request))
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def _abort_app(runtime: ControlPlaneRuntimeService) -> ControlPlaneApplication:
    return ControlPlaneApplication(
        telemetry_service=_FakeTelemetryService(),
        runtime_service=runtime,
        story_service=_FakeStoryService(),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )


def _post_admin_abort(
    app: ControlPlaneApplication, *, op_id: str, body: dict[str, object]
) -> HttpResponse:
    return app.handle_request(
        method="POST",
        path=f"/v1/project-edge/operations/{op_id}/admin-abort",
        body=json.dumps(body).encode("utf-8"),
    )


_ABORT_BODY = {
    "session_id": "admin-sess-1",
    "principal_type": "operator",
    "reason": "hung executor; operator decision",
}


def test_admin_abort_endpoint_returns_aborted_200() -> None:
    """AC6: a clean abort returns 200 with the terminal ``aborted`` result."""
    runtime = _AbortRuntimeService(result=_abort_result("aborted"))
    app = _abort_app(runtime)

    response = _post_admin_abort(app, op_id="op-abort-1", body=_ABORT_BODY)

    assert response.status_code == HTTPStatus.OK
    body = _json_body(response)
    assert body["status"] == "aborted"
    assert body["edge_bundle"] is None
    assert "admin_abort_inflight_operation" in str(body["admin_note"])
    assert runtime.calls and runtime.calls[0][0] == "op-abort-1"


def test_admin_abort_endpoint_partial_write_returns_repair_200() -> None:
    """AC5/AC6: a partial write target returns 200 with the explicit ``repair`` state."""
    app = _abort_app(_AbortRuntimeService(result=_abort_result("repair")))

    response = _post_admin_abort(app, op_id="op-abort-1", body=_ABORT_BODY)

    assert response.status_code == HTTPStatus.OK
    assert _json_body(response)["status"] == "repair"


def test_admin_abort_endpoint_repair_resolve_returns_resolved_200() -> None:
    """AC10: admin-abort of an open ``repair`` target returns 200 ``resolved``.

    The HTTP adapter maps the productive repair-lock exit (repair -> ``resolved``)
    like any other successful terminal result (200), carrying the audited note.
    """
    app = _abort_app(_AbortRuntimeService(result=_abort_result("resolved")))

    response = _post_admin_abort(app, op_id="op-abort-1", body=_ABORT_BODY)

    assert response.status_code == HTTPStatus.OK
    body = _json_body(response)
    assert body["status"] == "resolved"
    assert body["edge_bundle"] is None


def test_admin_abort_endpoint_unknown_op_returns_404() -> None:
    """AC6: an unknown op_id is a deterministic fail-closed 404."""
    from agentkit.backend.control_plane.runtime import OperationNotFoundError

    app = _abort_app(_AbortRuntimeService(error=OperationNotFoundError("op-abort-1")))

    response = _post_admin_abort(app, op_id="op-abort-1", body=_ABORT_BODY)

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "operation_not_found"


def test_admin_abort_endpoint_terminal_op_returns_409() -> None:
    """AC6: a target that is not a live claim is a deterministic fail-closed 409."""
    from agentkit.backend.control_plane.runtime import OperationNotAbortableError

    app = _abort_app(
        _AbortRuntimeService(
            error=OperationNotAbortableError("op-abort-1", "committed")
        )
    )

    response = _post_admin_abort(app, op_id="op-abort-1", body=_ABORT_BODY)

    assert response.status_code == HTTPStatus.CONFLICT
    body = _json_body(response)
    assert body["error_code"] == "operation_not_abortable"
    assert body["detail"] == {"current_status": "committed"}


def test_admin_abort_endpoint_invalid_payload_returns_400() -> None:
    """AC6: a payload missing the mandatory audited reason is a 400 (fail-closed)."""
    app = _abort_app(_AbortRuntimeService(result=_abort_result("aborted")))

    response = _post_admin_abort(
        app,
        op_id="op-abort-1",
        body={"session_id": "s", "principal_type": "operator"},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert _json_body(response)["error_code"] == "invalid_admin_abort_payload"


def test_phase_mutation_repair_lock_rejection_maps_to_409() -> None:
    """AC10: a repair-lock ``rejected`` mutation surfaces as HTTP 409 at the route.

    The AC10 mutation-lock returns a ``rejected`` ``ControlPlaneMutationResult``
    with a machine-readable reason; the phase-mutation route maps ``rejected`` to
    409 CONFLICT, so a mutating dispatch against a story in an open reconcile/repair
    state is deterministically rejected with a machine-readable reason.
    """

    class _RepairLockedRuntime(ControlPlaneRuntimeService):
        def start_phase(
            self, *, run_id: str, phase: str, request: object
        ) -> ControlPlaneMutationResult:
            del run_id, request
            return ControlPlaneMutationResult(
                status="rejected",
                op_id="op-blocked",
                operation_kind="phase_start",
                run_id="run-100",
                phase=phase,
                edge_bundle=None,
                phase_dispatch=PhaseDispatchResult(
                    phase=phase,
                    status="rejected",
                    reaction="rejected",
                    dispatched=False,
                    rejection_reason=(
                        "phase_start rejected: story has an open "
                        "reconcile/repair state (AG3-138 AC10)."
                    ),
                ),
            )

    app = _abort_app(_RepairLockedRuntime())
    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/start",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "principal_type": "orchestrator",
                "worktree_roots": ["T:/worktrees/ag3-100"],
                "op_id": "op-blocked",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.CONFLICT
    body = _json_body(response)
    assert body["status"] == "rejected"
    assert "repair" in str(body["phase_dispatch"]["rejection_reason"])


def test_phase_start_retry_against_aborted_terminal_row_maps_to_409() -> None:
    """AG3-140 r6 MAJOR (HTTP): a mutating retry of the same op_id against an
    ABORTED terminal ``control_plane_operations`` row, driven through the REAL
    phase-start route over the REAL runtime classification (only the in-memory
    store is seeded), maps to HTTP 409 conflict (``status='rejected'``) -- NOT a
    201 ``{status: aborted}`` replay. This is the duplicate-op_id classification of
    an existing non-committed terminal, not a fresh repair-lock rejection. The
    verbatim aborted payload is preserved only on the reconcile GET path.
    """
    from tests.unit.control_plane.test_runtime import (
        _admitting_service,
        _RepoState,
        _resolvable_standard_ctx,
        _retry_request,
        _seed_terminal_operation,
    )

    state = _RepoState()
    _resolvable_standard_ctx(state)
    request = _retry_request("op-abort-http")
    _seed_terminal_operation(
        state, op_id="op-abort-http", status="aborted", request=request
    )
    app = _abort_app(_admitting_service(state))

    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/start",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "principal_type": "orchestrator",
                "worktree_roots": ["T:/worktrees/ag3-100"],
                "op_id": "op-abort-http",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.CONFLICT
    body = _json_body(response)
    assert body["status"] == "rejected"
    # The aborted terminal row was neither replayed-as-success nor overwritten.
    assert state.operations["op-abort-http"].status == "aborted"


def test_phase_mutation_body_hash_mismatch_maps_to_409() -> None:
    """AG3-140 finding 3: a reused op_id with a different body -> 409 idempotency_mismatch.

    The runtime raises ``IdempotencyMismatchError`` when a terminal op_id is
    replayed with a different request body-hash; the phase-mutation route maps it
    to HTTP 409 ``idempotency_mismatch`` (not a wrong replay of the stored result).
    """
    from agentkit.backend.story_context_manager.errors import IdempotencyMismatchError

    class _MismatchRuntime(ControlPlaneRuntimeService):
        def start_phase(
            self, *, run_id: str, phase: str, request: object
        ) -> ControlPlaneMutationResult:
            del run_id, phase, request
            raise IdempotencyMismatchError(
                "op_id 'op-x' was previously used with a different request body; "
                "use a new op_id for a different mutation",
                detail={"op_id": "op-x", "conflict": "body_hash_mismatch"},
            )

    app = _abort_app(_MismatchRuntime())
    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/phases/setup/start",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "principal_type": "orchestrator",
                "worktree_roots": ["T:/worktrees/ag3-100"],
                "op_id": "op-x",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.CONFLICT
    body = _json_body(response)
    assert body["error_code"] == "idempotency_mismatch"
    assert body["detail"]["conflict"] == "body_hash_mismatch"


def test_closure_complete_repair_lock_rejection_maps_to_409() -> None:
    """AC10 (AG3-138 P2): a repair-locked closure-complete surfaces as HTTP 409.

    The closure-complete route is a MUTATING entrypoint: a ``rejected`` result (the
    AC10 open-reconcile/repair mutation lock, or any other fail-closed closure
    rejection) must map to 409 CONFLICT, exactly like the phase-mutation route.
    Previously this route returned 201 CREATED unconditionally, letting a rejected
    closure masquerade as a success (fail-closed violation).
    """

    class _RepairLockedClosureRuntime(ControlPlaneRuntimeService):
        def complete_closure(
            self, *, run_id: str, request: object
        ) -> ControlPlaneMutationResult:
            del request
            return ControlPlaneMutationResult(
                status="rejected",
                op_id="op-closure-blocked",
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                edge_bundle=None,
                phase_dispatch=PhaseDispatchResult(
                    phase="closure",
                    status="rejected",
                    reaction="rejected",
                    dispatched=False,
                    rejection_reason=(
                        "closure_complete rejected: story has an open "
                        "reconcile/repair state (AG3-138 AC10)."
                    ),
                ),
            )

    app = _abort_app(_RepairLockedClosureRuntime())
    response = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/story-runs/run-100/closure/complete",
        body=json.dumps(
            {
                "project_key": "tenant-a",
                "story_id": "AG3-100",
                "session_id": "sess-001",
                "op_id": "op-closure-blocked",
            },
        ).encode("utf-8"),
    )

    assert response.status_code == HTTPStatus.CONFLICT
    body = _json_body(response)
    assert body["status"] == "rejected"
    assert body["operation_kind"] == "closure_complete"
