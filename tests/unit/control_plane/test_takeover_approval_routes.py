from __future__ import annotations

import json
from http import HTTPStatus

from agentkit.backend.auth.middleware import AuthResult
from agentkit.backend.control_plane.takeover_approval_read import TakeoverApprovalsResponse
from agentkit.backend.control_plane_http.takeover_approval_routes import TakeoverApprovalRoutes


class _ApprovalSource:
    def __init__(self) -> None:
        self.calls = 0

    def list_open_takeover_approvals(self) -> TakeoverApprovalsResponse:
        self.calls += 1
        return TakeoverApprovalsResponse()


def test_takeover_approval_read_rejects_missing_or_token_auth_before_port_read() -> None:
    source = _ApprovalSource()
    routes = TakeoverApprovalRoutes(source)

    missing = routes.handle_get("/v1/governance/takeover-approvals", "corr-1", None)
    token = routes.handle_get(
        "/v1/governance/takeover-approvals",
        "corr-2",
        AuthResult(auth_kind="project_api_token", project_key="tenant-a"),
    )

    assert missing is not None and missing.status_code == HTTPStatus.FORBIDDEN
    assert token is not None and token.status_code == HTTPStatus.FORBIDDEN
    assert json.loads(token.body)["error_code"] == "forbidden"
    assert source.calls == 0


def test_takeover_approval_read_accepts_only_human_bff_session() -> None:
    source = _ApprovalSource()
    routes = TakeoverApprovalRoutes(source)

    response = routes.handle_get(
        "/v1/governance/takeover-approvals",
        "corr-human",
        AuthResult(auth_kind="strategist_session", session_id="human-1"),
    )

    assert response is not None and response.status_code == HTTPStatus.OK
    assert json.loads(response.body) == {"approvals": [], "challenges": []}
    assert source.calls == 1
