"""Productive adapter for the takeover-approval frontend read port."""

from __future__ import annotations

from dataclasses import dataclass

from agentkit.backend.control_plane.takeover_approval_read import TakeoverApprovalsResponse
from agentkit.backend.state_backend.story_lifecycle_store import (
    list_open_takeover_approval_requests_global,
)


@dataclass(frozen=True)
class StateBackendTakeoverApprovalReadSource:
    """Delegate cross-project approval reads to the sanctioned facade."""

    def list_open_takeover_approvals(self) -> TakeoverApprovalsResponse:
        """Return the joined Postgres-only frontend approval projection."""
        response = list_open_takeover_approval_requests_global()
        if not isinstance(response, TakeoverApprovalsResponse):
            raise TypeError("takeover approval facade returned an invalid response")
        return response


__all__ = ["StateBackendTakeoverApprovalReadSource"]
