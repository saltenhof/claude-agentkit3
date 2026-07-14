"""Published read port for cross-project takeover approvals."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.backend.control_plane.takeover_approval_read import (
        TakeoverApprovalsResponse,
    )


@runtime_checkable
class TakeoverApprovalReadSource(Protocol):
    """Read the open frontend approval projection across all projects."""

    def list_open_takeover_approvals(self) -> TakeoverApprovalsResponse:
        """Return open approvals joined to current owner-BC challenges."""
        ...


__all__ = ["TakeoverApprovalReadSource"]
