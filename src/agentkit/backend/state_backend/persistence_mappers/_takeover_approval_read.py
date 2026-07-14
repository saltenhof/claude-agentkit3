"""Joined takeover-approval frontend read mapper."""

from __future__ import annotations

import logging
from typing import Any

from agentkit.backend.control_plane.ownership_transfer import LOSS_CORRIDOR_TEXT
from agentkit.backend.control_plane.takeover_approval_read import (
    TakeoverApprovalRequest,
    TakeoverApprovalsResponse,
    TakeoverChallengeNotice,
    TakeoverRepoPushStatus,
)

from ._control_plane import takeover_approval_row_to_record, takeover_challenge_row_to_record

logger = logging.getLogger(__name__)


def takeover_approval_read_rows_to_response(
    rows: list[dict[str, Any]],
) -> TakeoverApprovalsResponse:
    """Map joined approval/challenge rows to the exact frontend contract."""
    approvals: list[TakeoverApprovalRequest] = []
    challenges: list[TakeoverChallengeNotice] = []
    for row in rows:
        approval = takeover_approval_row_to_record(row)
        challenge_row = row.get("challenge_row")
        if not isinstance(challenge_row, dict):
            _log_omitted_approval(approval.approval_id, "missing_joined_challenge")
            continue
        challenge = takeover_challenge_row_to_record(challenge_row)
        if challenge.status != "pending":
            _log_omitted_approval(approval.approval_id, "challenge_not_pending")
            continue
        approvals.append(
            TakeoverApprovalRequest(
                approval_id=approval.approval_id,
                challenge_id=challenge.challenge_id,
                project_key=approval.project_key,
                story_id=approval.story_id,
                run_id=approval.run_id,
                requested_by_principal=approval.requested_by_principal_type,
                reason=approval.reason,
                owner_session_id=challenge.owner_session_id,
                ownership_epoch=challenge.ownership_epoch,
                binding_version=int(challenge.binding_version),
                phase=challenge.phase_status,
                open_operation_ids=list(challenge.open_operation_ids),
                repo_push_status=[
                    TakeoverRepoPushStatus(
                        repo_id=repo.repo_id,
                        last_pushed_head_sha=repo.takeover_base_sha,
                        last_push_at=repo.last_push_at,
                        push_lag_hint=repo.push_lag_hint,
                    )
                    for repo in challenge.repos
                ],
                takeover_history_count=len(challenge.takeover_history_refs),
                status=approval.status.value,
                requested_at=approval.requested_at,
                expires_at=approval.expires_at,
            )
        )
        challenges.append(
            TakeoverChallengeNotice(
                challenge_id=challenge.challenge_id,
                loss_corridor_notice_key="pushed_only_loss_corridor",
                loss_corridor_notice_text=LOSS_CORRIDOR_TEXT,
            )
        )
    return TakeoverApprovalsResponse(approvals=approvals, challenges=challenges)


def _log_omitted_approval(approval_id: str, reason: str) -> None:
    logger.warning(
        "takeover_approval_row_omitted approval_id=%s reason=%s",
        approval_id,
        reason,
    )


__all__ = ["takeover_approval_read_rows_to_response"]
