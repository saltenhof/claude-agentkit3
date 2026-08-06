"""HTTPS wire models for the writer-owned story-exit operation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StoryExitMutationRequest(BaseModel):
    """Authenticated administrative exit request without identity attestations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str
    run_id: str
    reason: str
    note: str | None = None


class StoryExitMutationResponse(BaseModel):
    """Committed story-exit result returned by the active writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    exit_id: str
    story_id: str
    operating_mode: str
    artifact_dir: str


__all__ = ["StoryExitMutationRequest", "StoryExitMutationResponse"]
