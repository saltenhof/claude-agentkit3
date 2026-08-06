"""Typed HTTP contract for the administrative story-split mutation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StorySplitMutationRequest(BaseModel):
    """Wire request consumed by the single control-plane writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_text: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    project_root: str = Field(min_length=1)


class StorySplitMutationResponse(BaseModel):
    """Stable terminal response returned by the writer-owned split route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    split_id: str
    source_story_id: str
    successor_ids: tuple[str, ...]
    resumed: bool


__all__ = ["StorySplitMutationRequest", "StorySplitMutationResponse"]
