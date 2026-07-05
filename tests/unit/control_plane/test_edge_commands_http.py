"""HTTP-layer tests for the Edge-Command-Queue endpoints (FK-91 §91.1b, AG3-145).

Mirrors ``tests/unit/control_plane/test_http.py``'s admin-abort HTTP pattern:
a fake ``ControlPlaneRuntimeService`` wired directly into ``ControlPlaneApplication``
(no database, no real story/dashboard wiring). Covers AC1 (GET ack + session
scope, 400 on missing query params), AC2 (POST result: missing op_id -> 422,
unknown command -> 404, wire dispatch) and AC3 (403 mapping for
``ownership_transferred``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from typing import cast

from tests.story_read_port_stub import StubStoryReadPort

from agentkit.backend.control_plane.http import ControlPlaneApplication, HttpResponse
from agentkit.backend.control_plane.models import (
    EdgeCommandMutationResult,
    EdgeCommandResultRequest,
    EdgeCommandView,
    OpenEdgeCommandsResponse,
    OwnershipTransferredDetail,
)
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.story.service import StoryService

_NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


class _FakeStoryService(StoryService):
    def __init__(self) -> None:
        super().__init__(repository=StubStoryReadPort())


class _NoopTenantScopeMiddleware:
    """Passthrough tenant-scope stub (unused by non-project-scoped edge routes)."""

    def validate(self, *, method: str, route_path: str, correlation_id: str) -> None:
        return None


class _FakeEdgeCommandRuntimeService(ControlPlaneRuntimeService):
    def __init__(
        self,
        *,
        open_commands: OpenEdgeCommandsResponse | None = None,
        result: EdgeCommandMutationResult | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self._open_commands = open_commands or OpenEdgeCommandsResponse()
        self._result = result
        self.error = error
        self.get_calls: list[tuple[str, str, str]] = []
        self.post_calls: list[tuple[str, EdgeCommandResultRequest]] = []

    def list_and_ack_open_commands(
        self, run_id: str, *, project_key: str, session_id: str,
    ) -> OpenEdgeCommandsResponse:
        if self.error is not None:
            raise self.error
        self.get_calls.append((run_id, project_key, session_id))
        return self._open_commands

    def submit_command_result(
        self, command_id: str, request: EdgeCommandResultRequest,
    ) -> EdgeCommandMutationResult:
        if self.error is not None:
            raise self.error
        self.post_calls.append((command_id, request))
        assert self._result is not None
        return self._result


def _app(runtime: ControlPlaneRuntimeService) -> ControlPlaneApplication:
    return ControlPlaneApplication(
        runtime_service=runtime,
        story_service=_FakeStoryService(),
        tenant_scope_middleware=_NoopTenantScopeMiddleware(),  # type: ignore[arg-type]
    )


def _json_body(response: HttpResponse) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(response.body))


# ---------------------------------------------------------------------------
# AC1: GET .../story-runs/{run_id}/commands
# ---------------------------------------------------------------------------


def test_get_open_commands_returns_the_wired_response() -> None:
    runtime = _FakeEdgeCommandRuntimeService(
        open_commands=OpenEdgeCommandsResponse(
            commands=[
                EdgeCommandView(
                    command_id="cmd-1",
                    command_kind="provision_worktree",
                    payload={"repo_id": "repo-a"},
                    status="delivered",
                    created_at=_NOW,
                )
            ]
        )
    )
    app = _app(runtime)

    response = app.handle_request(
        method="GET",
        path="/v1/project-edge/story-runs/run-1/commands?project_key=tenant-a&session_id=sess-A",
        body=b"",
    )

    assert response.status_code == HTTPStatus.OK
    body = _json_body(response)
    commands = cast("list[dict[str, object]]", body["commands"])
    assert len(commands) == 1
    assert commands[0]["command_id"] == "cmd-1"
    assert runtime.get_calls == [("run-1", "tenant-a", "sess-A")]


def test_get_open_commands_missing_query_params_returns_400() -> None:
    app = _app(_FakeEdgeCommandRuntimeService())

    response = app.handle_request(
        method="GET",
        path="/v1/project-edge/story-runs/run-1/commands",
        body=b"",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert _json_body(response)["error_code"] == "invalid_edge_commands_query"


def test_get_open_commands_missing_session_id_only_returns_400() -> None:
    app = _app(_FakeEdgeCommandRuntimeService())

    response = app.handle_request(
        method="GET",
        path="/v1/project-edge/story-runs/run-1/commands?project_key=tenant-a",
        body=b"",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


# ---------------------------------------------------------------------------
# AC2/AC3: POST .../commands/{command_id}/result
# ---------------------------------------------------------------------------


_RESULT_BODY = {
    "project_key": "tenant-a",
    "story_id": "AG3-100",
    "session_id": "sess-A",
    "op_id": "op-1",
    "result": {
        "result_type": "worktree_report",
        "repo_id": "repo-a",
        "outcome": "provisioned",
        "worktree_root": "/wt/AG3-100",
    },
}


def _post_result(app: ControlPlaneApplication, *, command_id: str, body: dict[str, object]) -> HttpResponse:
    return app.handle_request(
        method="POST",
        path=f"/v1/project-edge/commands/{command_id}/result",
        body=json.dumps(body).encode("utf-8"),
    )


def test_post_command_result_completed_returns_201() -> None:
    runtime = _FakeEdgeCommandRuntimeService(
        result=EdgeCommandMutationResult(
            status="completed", command_id="cmd-1", op_id="op-1",
        )
    )
    app = _app(runtime)

    response = _post_result(app, command_id="cmd-1", body=_RESULT_BODY)

    assert response.status_code == HTTPStatus.CREATED
    body = _json_body(response)
    assert body["status"] == "completed"
    assert len(runtime.post_calls) == 1
    assert runtime.post_calls[0][0] == "cmd-1"
    assert runtime.post_calls[0][1].op_id == "op-1"


def test_post_command_result_missing_op_id_returns_422() -> None:
    app = _app(_FakeEdgeCommandRuntimeService())
    body = {k: v for k, v in _RESULT_BODY.items() if k != "op_id"}

    response = _post_result(app, command_id="cmd-1", body=body)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _json_body(response)["error_code"] == "invalid_edge_command_result_payload"


def test_post_command_result_unknown_command_returns_404() -> None:
    runtime = _FakeEdgeCommandRuntimeService(
        result=EdgeCommandMutationResult(
            status="rejected",
            command_id="cmd-missing",
            op_id="op-1",
            error_code="edge_command_not_found",
        )
    )
    app = _app(runtime)

    response = _post_result(app, command_id="cmd-missing", body=_RESULT_BODY)

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_post_command_result_already_resolved_returns_409() -> None:
    runtime = _FakeEdgeCommandRuntimeService(
        result=EdgeCommandMutationResult(
            status="rejected",
            command_id="cmd-1",
            op_id="op-2",
            error_code="edge_command_already_resolved",
        )
    )
    app = _app(runtime)

    response = _post_result(app, command_id="cmd-1", body=_RESULT_BODY)

    assert response.status_code == HTTPStatus.CONFLICT


def test_post_command_result_ownership_transferred_returns_403() -> None:
    """AC3: the ex-owner rejection maps to 403, carrying the structured payload."""
    runtime = _FakeEdgeCommandRuntimeService(
        result=EdgeCommandMutationResult(
            status="rejected",
            command_id="cmd-1",
            op_id="op-1",
            error_code="ownership_transferred",
            ownership_conflict=OwnershipTransferredDetail(
                reason="ownership_transferred",
                new_owner_session_id="sess-NEW",
                new_ownership_epoch=2,
                transferred_at=_NOW,
            ),
        )
    )
    app = _app(runtime)

    response = _post_result(app, command_id="cmd-1", body=_RESULT_BODY)

    assert response.status_code == HTTPStatus.FORBIDDEN
    body = _json_body(response)
    ownership_conflict = cast("dict[str, object]", body["ownership_conflict"])
    assert ownership_conflict["new_owner_session_id"] == "sess-NEW"


def test_post_command_result_busy_object_claim_carries_retry_after_header() -> None:
    runtime = _FakeEdgeCommandRuntimeService(
        result=EdgeCommandMutationResult(
            status="rejected",
            command_id="cmd-1",
            op_id="op-1",
            error_code="conflict",
            retry_after_seconds=2,
        )
    )
    app = _app(runtime)

    response = _post_result(app, command_id="cmd-1", body=_RESULT_BODY)

    assert response.status_code == HTTPStatus.CONFLICT
    headers = dict(response.headers)
    assert headers["Retry-After"] == "2"
