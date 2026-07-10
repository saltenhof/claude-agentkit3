"""Boundary-constructed ownership-transfer commands with attested identity."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agentkit.backend.control_plane.models import (
    TakeoverConfirmRequest,
    TakeoverDenyRequest,
)
from agentkit.backend.governance.principal_capabilities.principals import Principal


class TakeoverConfirmCommand(BaseModel):
    """Internal confirm command constructed from wire input and auth evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: TakeoverConfirmRequest
    confirmed_by_session_id: str = Field(min_length=1)
    confirmed_by_principal: Principal


class TakeoverDenyCommand(BaseModel):
    """Internal denial command constructed from wire input and auth evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: TakeoverDenyRequest
    denied_by_session_id: str = Field(min_length=1)
    denied_by_principal: Principal


__all__ = ["TakeoverConfirmCommand", "TakeoverDenyCommand"]
