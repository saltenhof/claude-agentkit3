"""Domain models for requirements coverage."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class StoryAreLinkKind(StrEnum):
    """Typed Story-to-ARE relation kind."""

    ADDRESSES = "addresses"
    PARTIAL = "partial"
    DERIVES_FROM = "derives_from"
    RECURRING = "recurring"


class StoryAreLink(BaseModel):
    """Edge between one AK3 story and one opaque external ARE item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    are_item_id: str
    kind: StoryAreLinkKind
