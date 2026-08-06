"""HTTPS wire models for the writer-owned story-reset operation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StoryResetMutationRequest(BaseModel):
    """Authenticated administrative reset request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str
    reason: str
    project_root: str
    escalation_ref: str | None = None
    dry_run: bool = False
    force: bool = False


class StoryResetMutationResponse(BaseModel):
    """Plan or committed reset result returned by the active writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: str
    status: str
    reset_id: str
    story_id: str
    run_id: str | None = None
    planned_domains: tuple[str, ...] = ()
    clean_state: bool | None = None
    purge_summary: dict[str, int] = {}
    resumed: bool = False


__all__ = ["StoryResetMutationRequest", "StoryResetMutationResponse"]
