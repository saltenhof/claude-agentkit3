from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agentkit.backend.control_plane.ownership import TakeoverApprovalStatus
from agentkit.backend.control_plane.records import (
    TakeoverApprovalRecord,
    TakeoverChallengeRecord,
    TakeoverChallengeRepoRecord,
)
from agentkit.backend.control_plane.takeover_approval_read import TakeoverApprovalRequest
from agentkit.backend.state_backend.persistence_mappers import (
    takeover_approval_read_rows_to_response,
    takeover_approval_to_row,
    takeover_challenge_to_row,
)
from agentkit.backend.telemetry.sse_stream import (
    iter_governance_sse_stream,
    iter_project_sse_stream,
)

_ENTITY_FIELDS = {
    "approval_id", "challenge_id", "project_key", "story_id", "run_id",
    "requested_by_principal", "reason", "owner_session_id", "ownership_epoch",
    "binding_version", "phase", "last_api_contact_at", "open_operation_ids",
    "repo_push_status", "takeover_history_count", "status", "requested_at", "expires_at",
}


class _Source:
    def __init__(self, approval: TakeoverApprovalRecord) -> None:
        self.approval = approval

    def events_for_project(self, project_key: str, *, limit: int = 200) -> list[object]:
        del project_key, limit
        return []

    def pending_takeover_approvals_for_project(
        self, project_key: str | None,
    ) -> tuple[TakeoverApprovalRecord, ...]:
        if project_key is None or project_key == self.approval.project_key:
            return (self.approval,)
        return ()


def test_global_and_project_stream_use_byte_identical_takeover_envelope() -> None:
    approval, _ = _records()
    source = _Source(approval)

    project_chunk = next(iter_project_sse_stream(
        project_key="tenant-y", source=source, topics={"governance"}, poll_interval_seconds=0,
    ))
    global_chunk = next(iter_governance_sse_stream(
        source=source, topics={"governance"}, poll_interval_seconds=0,
    ))

    assert global_chunk == project_chunk


def test_approval_read_model_is_field_exact_v3_and_carries_owner_notice() -> None:
    approval, challenge = _records()
    row = takeover_approval_to_row(approval)
    row["challenge_row"] = takeover_challenge_to_row(challenge)

    response = takeover_approval_read_rows_to_response([row]).model_dump(mode="json")
    projected = response["approvals"][0]

    assert set(projected) == _ENTITY_FIELDS
    statuses = {"pending", "approved", "denied", "expired", "invalidated"}
    assert {
        TakeoverApprovalRequest.model_validate({**projected, "status": status}).status
        for status in statuses
    } == statuses
    assert set(projected["repo_push_status"][0]) == {
        "repo_id", "last_pushed_head_sha", "last_push_at", "push_lag_hint",
    }
    assert "dirty" not in str(projected).lower()
    assert response["challenges"][0]["loss_corridor_notice_key"] == "pushed_only_loss_corridor"
    assert "Unpushed commits" in response["challenges"][0]["loss_corridor_notice_text"]


def test_frontend_commands_and_ui_contract_are_pinned_without_js_runner() -> None:
    root = Path(__file__).parents[3]
    api_source = (root / "src/agentkit/frontend/app/api.ts").read_text(encoding="utf-8")
    overlay_source = (
        root / "src/agentkit/frontend/app/contexts/story_context_manager/components/TakeoverApprovalOverlay.tsx"
    ).read_text(encoding="utf-8")

    assert "takeover-request" in api_source and "reason" in api_source and "makeOpId()" in api_source
    assert "takeover-confirm" in api_source and "challenge_id: approval.challenge_id" in api_source
    takeover_types = (
        root / "src/agentkit/frontend/app/contexts/story_context_manager/takeoverTypes.ts"
    ).read_text(encoding="utf-8")
    command_contract = (
        root / "concept/formal-spec/frontend-contracts/commands.md"
    ).read_text(encoding="utf-8")
    assert "challenge_reissued" in takeover_types
    assert all(code in api_source for code in ["ApiError", "status", "errorCode", "correlationId"])
    assert all(
        code in command_contract
        for code in ["409", "403", "404", "idempotency_mismatch"]
    )
    assert "loss_corridor_notice_text" in overlay_source
    assert "loss_corridor_notice_key === 'pushed_only_loss_corridor'" in overlay_source
    assert "corridorText.trim().length > 0" in overlay_source
    assert "repo.last_pushed_head_sha.trim().length > 0" in overlay_source
    assert "last_pushed_head_sha" in overlay_source


def test_shell_overlay_and_takeover_cockpit_ui_contract_are_source_pinned() -> None:
    root = Path(__file__).parents[3] / "src/agentkit/frontend/app"
    app_source = (root / "App.tsx").read_text(encoding="utf-8")
    shell_source = (root / "app_shell/layout/Shell.tsx").read_text(encoding="utf-8")
    panel_source = (
        root / "contexts/story_context_manager/components/TakeoverPanel.tsx"
    ).read_text(encoding="utf-8")

    assert "/v1/projects/${encodeURIComponent(selectedProjectKey)}/events?topics=" in app_source
    assert "stories,phases,planning,telemetry,coverage" in app_source
    assert "/v1/events/governance?topics=governance" in app_source
    assert "withCredentials: true" in app_source
    assert '<div className="shell-overlay-region" aria-live="assertive">{overlay}</div>' in shell_source
    assert "approval.status" not in shell_source
    assert all(
        field in panel_source
        for field in [
            "owner_session_id", "ownership_epoch", "last_api_contact_at",
            "open_operation_ids", "last_pushed_head_sha", "last_push_at",
            "push_lag_hint", "takeover_base_sha", "takeover_history_count",
        ]
    )
    assert "Inaktivität ist keine Diagnose" in panel_source
    assert "worktree_dirty" not in panel_source
    assert all(
        state in panel_source
        for state in [
            "takeover_reconcile_required", "contested_local_writes",
            "remote_branch_diverged_after_takeover",
            "local_stale_or_dirty_takeover_target",
        ]
    )
    assert "Signal unbekannt – blockierend (fail-closed)." in panel_source


def _records() -> tuple[TakeoverApprovalRecord, TakeoverChallengeRecord]:
    now = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
    approval = TakeoverApprovalRecord(
        approval_id="approval-y", project_key="tenant-y", story_id="AG3-153", run_id="run-y",
        requested_by_session_id="agent-y", requested_by_principal_type="interactive_agent",
        reason="owner unavailable", challenge_ref="challenge-y",
        status=TakeoverApprovalStatus.PENDING, requested_at=now,
        expires_at=datetime(2026, 7, 14, 10, 15, tzinfo=UTC),
    )
    challenge = TakeoverChallengeRecord(
        challenge_id="challenge-y", request_op_id="op-request", project_key="tenant-y",
        story_id="AG3-153", run_id="run-y", requesting_session_id="agent-y",
        requesting_principal_type="interactive_agent", requesting_worktree_roots=("T:/worktree",),
        reason="owner unavailable", owner_session_id="owner-y", ownership_epoch=4,
        binding_version="3", phase_status="implementation", issued_at=now,
        expires_at=datetime(2026, 7, 14, 10, 15, tzinfo=UTC),
        repos=(TakeoverChallengeRepoRecord("api", "abc123", now, "fresh", "verified"),),
        open_operation_ids=("op-running",), takeover_history_refs=("transfer-1",),
    )
    return approval, challenge
