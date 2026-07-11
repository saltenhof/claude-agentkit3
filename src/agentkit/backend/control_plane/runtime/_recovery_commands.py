"""Boundary-constructed recovery command with attested identity."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agentkit.backend.control_plane.models import RecoveryRequest


class RecoveryCommand(BaseModel):
    """Internal recovery command constructed from wire and auth evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: RecoveryRequest
    superseded_run_id: str = Field(min_length=1)
    actor_session_id: str = Field(min_length=1)
    actor_principal_type: str = Field(min_length=1)


__all__ = ["RecoveryCommand"]
