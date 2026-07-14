from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus

import pytest

from agentkit.backend.auth.middleware import AuthResult
from agentkit.backend.control_plane.ownership import TakeoverApprovalStatus
from agentkit.backend.control_plane.records import TakeoverApprovalRecord
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.http.routes import TelemetryRoutes
from agentkit.backend.telemetry.sse_stream import (
    iter_governance_sse_stream,
    parse_governance_topics,
)


class _ApprovalSource:
    def __init__(
        self,
        approval: TakeoverApprovalRecord | None,
        *,
        approval_events: list[ExecutionEventRecord] | None = None,
    ) -> None:
        self.approval = approval
        self.approval_events = approval_events or []
        self.scopes: list[str | None] = []
        self.global_event_reads = 0

    def events_for_project(self, project_key: str, *, limit: int = 200) -> list[ExecutionEventRecord]:
        del project_key, limit
        return []

    def pending_takeover_approvals_for_project(
        self, project_key: str | None,
    ) -> tuple[TakeoverApprovalRecord, ...]:
        self.scopes.append(project_key)
        return (self.approval,) if self.approval is not None else ()

    def takeover_approval_events_global(
        self,
        *,
        limit: int = 200,
    ) -> list[ExecutionEventRecord]:
        del limit
        self.global_event_reads += 1
        return self.approval_events


def test_governance_stream_reads_all_projects_through_none_scope() -> None:
    source = _ApprovalSource(_approval())
    stream = iter_governance_sse_stream(
        source=source,
        topics={"governance"},
        poll_interval_seconds=0,
    )

    chunk = next(stream)

    assert source.scopes == [None]
    assert b'"project_key": "tenant-y"' in chunk
    assert b'"approval_id": "approval-y"' in chunk


def test_governance_stream_includes_cross_project_approval_change_events() -> None:
    source = _ApprovalSource(None, approval_events=[_approval_changed_event()])
    stream = iter_governance_sse_stream(
        source=source,
        topics={"governance"},
        poll_interval_seconds=0,
    )

    chunk = next(stream)

    assert source.global_event_reads == 1
    assert b'"event_type": "takeover_approval_changed"' in chunk
    assert b'"project_key": "tenant-y"' in chunk


def test_governance_topic_filter_is_fail_closed() -> None:
    assert parse_governance_topics(None) == frozenset({"governance"})
    assert parse_governance_topics("governance") == frozenset({"governance"})
    with pytest.raises(ValueError, match="Unknown SSE topic"):
        parse_governance_topics("stories")
    with pytest.raises(ValueError, match="Unknown SSE topic"):
        parse_governance_topics("unknown")


def test_governance_route_requires_human_session_and_has_no_all_topic_peer() -> None:
    source = _ApprovalSource(_approval())
    routes = TelemetryRoutes(source)

    missing = routes.handle_get("/v1/events/governance", {}, "corr-none")
    token = routes.handle_get(
        "/v1/events/governance",
        {},
        "corr-token",
        AuthResult(auth_kind="project_api_token", project_key="tenant-y"),
    )
    absent = routes.handle_get(
        "/v1/events",
        {},
        "corr-absent",
        AuthResult(auth_kind="strategist_session", session_id="human-1"),
    )

    assert missing is not None and missing.status_code == HTTPStatus.FORBIDDEN
    assert token is not None and token.status_code == HTTPStatus.FORBIDDEN
    assert absent is None


def test_governance_route_filters_topics_and_returns_global_stream() -> None:
    routes = TelemetryRoutes(_ApprovalSource(_approval()))
    auth = AuthResult(auth_kind="strategist_session", session_id="human-1")

    invalid = routes.handle_get(
        "/v1/events/governance", {"topics": ["stories"]}, "corr-bad", auth,
    )
    response = routes.handle_get(
        "/v1/events/governance", {"topics": ["governance"]}, "corr-ok", auth,
    )

    assert invalid is not None and invalid.status_code == HTTPStatus.BAD_REQUEST
    assert response is not None and response.status_code == HTTPStatus.OK
    assert response.stream is not None
    assert b'"approval_id": "approval-y"' in next(iter(response.stream))


def _approval() -> TakeoverApprovalRecord:
    return TakeoverApprovalRecord(
        approval_id="approval-y",
        project_key="tenant-y",
        story_id="AG3-153",
        run_id="run-y",
        requested_by_session_id="agent-y",
        requested_by_principal_type="interactive_agent",
        reason="owner unavailable",
        challenge_ref="challenge-y",
        status=TakeoverApprovalStatus.PENDING,
        requested_at=datetime(2026, 7, 14, 10, 0, tzinfo=UTC),
        expires_at=datetime(2026, 7, 14, 10, 15, tzinfo=UTC),
    )


def _approval_changed_event() -> ExecutionEventRecord:
    return ExecutionEventRecord(
        project_key="tenant-y",
        story_id="AG3-153",
        run_id="run-y",
        event_id="event-denied-y",
        event_type="takeover_approval_changed",
        occurred_at=datetime(2026, 7, 14, 10, 5, tzinfo=UTC),
        source_component="story-lifecycle",
        severity="info",
        phase="ownership",
        payload={"approval_id": "approval-y", "status": "denied"},
    )
