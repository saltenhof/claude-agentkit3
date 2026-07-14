"""Postgres integration coverage for AG3-153 global takeover reads."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus

import pytest

from agentkit.backend.auth.middleware import AuthResult
from agentkit.backend.control_plane.ownership import TakeoverApprovalStatus
from agentkit.backend.control_plane.records import (
    TakeoverApprovalRecord,
    TakeoverChallengeRecord,
    TakeoverChallengeRepoRecord,
)
from agentkit.backend.control_plane_http.takeover_approval_routes import TakeoverApprovalRoutes
from agentkit.backend.state_backend.store.takeover_approval_read_repository import (
    StateBackendTakeoverApprovalReadSource,
)
from agentkit.backend.state_backend.store.telemetry_read_repository import (
    StateBackendProjectTelemetryEventSource,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    insert_takeover_approval_global,
    insert_takeover_challenge_global,
    list_open_takeover_approval_requests_global,
)
from agentkit.backend.telemetry.sse_stream import iter_governance_sse_stream

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
_LATER = datetime(2026, 7, 14, 10, 15, tzinfo=UTC)


def test_project_y_approval_is_visible_globally_without_project_selection(
    postgres_backend_env: object,
) -> None:
    del postgres_backend_env
    _insert_pair("y", TakeoverApprovalStatus.PENDING)

    response = list_open_takeover_approval_requests_global()
    stream = iter_governance_sse_stream(
        source=StateBackendProjectTelemetryEventSource(),
        topics={"governance"},
        poll_interval_seconds=0,
    )

    assert [item.project_key for item in response.approvals] == ["tenant-y"]
    assert b'"project_key": "tenant-y"' in next(stream)


def test_reconnect_initial_get_recovers_drop_and_reopens_approved_fresh_challenge(
    postgres_backend_env: object,
) -> None:
    del postgres_backend_env
    _insert_pair("dropped", TakeoverApprovalStatus.PENDING)
    _insert_pair("reconnect", TakeoverApprovalStatus.APPROVED)
    dropped_stream = iter_governance_sse_stream(
        source=StateBackendProjectTelemetryEventSource(),
        topics={"governance"},
        poll_interval_seconds=0,
    )
    dropped_event = next(dropped_stream)
    dropped_stream.close()
    routes = TakeoverApprovalRoutes(StateBackendTakeoverApprovalReadSource())

    response = routes.handle_get(
        "/v1/governance/takeover-approvals",
        "corr-reconnect",
        AuthResult(auth_kind="strategist_session", session_id="human-reviewer"),
    )

    assert b'"approval_id": "approval-dropped"' in dropped_event
    assert response is not None and response.status_code == HTTPStatus.OK
    body = json.loads(response.body)
    reconnect = next(
        approval
        for approval in body["approvals"]
        if approval["approval_id"] == "approval-reconnect"
    )
    assert reconnect["status"] == "approved"
    assert reconnect["challenge_id"] == "challenge-reconnect"
    assert "challenge-reconnect" in {
        challenge["challenge_id"] for challenge in body["challenges"]
    }


@pytest.mark.parametrize(
    "auth_result",
    [
        None,
        AuthResult(auth_kind="project_api_token", project_key="tenant-y"),
    ],
)
def test_global_reads_reject_missing_session_and_project_token_before_postgres_access(
    postgres_backend_env: object,
    auth_result: AuthResult | None,
) -> None:
    del postgres_backend_env
    routes = TakeoverApprovalRoutes(StateBackendTakeoverApprovalReadSource())

    response = routes.handle_get(
        "/v1/governance/takeover-approvals",
        "corr-token",
        auth_result,
    )

    assert response is not None and response.status_code == HTTPStatus.FORBIDDEN
    assert json.loads(response.body)["error_code"] == "forbidden"


def _insert_pair(suffix: str, status: TakeoverApprovalStatus) -> None:
    challenge = TakeoverChallengeRecord(
        challenge_id=f"challenge-{suffix}", request_op_id=f"op-{suffix}",
        project_key="tenant-y", story_id=f"AG3-{suffix}", run_id=f"run-{suffix}",
        requesting_session_id=f"agent-{suffix}", requesting_principal_type="interactive_agent",
        requesting_worktree_roots=(f"T:/worktrees/{suffix}",), reason="owner unavailable",
        owner_session_id="owner-y", ownership_epoch=2, binding_version="4",
        phase_status="implementation", issued_at=_NOW, expires_at=_LATER,
        repos=(TakeoverChallengeRepoRecord("api", "abc123", _NOW, "fresh", "verified"),),
        open_operation_ids=(f"op-running-{suffix}",), takeover_history_refs=("transfer-1",),
    )
    approval = TakeoverApprovalRecord(
        approval_id=f"approval-{suffix}", project_key="tenant-y",
        story_id=f"AG3-{suffix}", run_id=f"run-{suffix}",
        requested_by_session_id=f"agent-{suffix}",
        requested_by_principal_type="interactive_agent", reason="owner unavailable",
        challenge_ref=challenge.challenge_id, status=status, requested_at=_NOW,
        expires_at=_LATER, decided_at=(_NOW if status is not TakeoverApprovalStatus.PENDING else None),
        decided_by_session_id=("human-reviewer" if status is TakeoverApprovalStatus.APPROVED else None),
    )
    insert_takeover_challenge_global(challenge)
    insert_takeover_approval_global(approval)
