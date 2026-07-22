"""Strict MCP wire models (AG3-174 R06 / AC 10).

``ConfigDict(strict=True, extra="forbid")`` — no bool-as-int, no int-as-bool,
no unknown fields. Used at the real MCP boundary before tool dispatch.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class StorySearchArgs(_StrictModel):
    query: str
    search_mode: Literal["hybrid", "vector", "keyword"] = "hybrid"
    project_id: str | None = None
    status: str | None = None
    story_type: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


class StoryListSourcesArgs(_StrictModel):
    project_id: str | None = None


class StorySyncArgs(_StrictModel):
    project_id: str | None = None
    full_reindex: bool = False


class ConceptSearchArgs(_StrictModel):
    query: str
    search_mode: Literal["hybrid", "vector", "keyword"] = "hybrid"
    project_id: str | None = None
    concept_id: str | None = None
    module: str | None = None
    is_appendix: bool | None = None
    concept_status: Literal["active", "draft", "archived"] = "active"
    limit: int = Field(default=10, ge=1, le=100)
    query_scopes: list[str] | None = None


class ConceptSyncArgs(_StrictModel):
    project_id: str | None = None
    full_reindex: bool = False
    concept_path: str | None = None


TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "story_search": StorySearchArgs,
    "story_list_sources": StoryListSourcesArgs,
    "story_sync": StorySyncArgs,
    "concept_search": ConceptSearchArgs,
    "concept_sync": ConceptSyncArgs,
}


def parse_tool_args(name: str, raw: dict[str, object]) -> dict[str, object]:
    """Parse raw MCP JSON arguments with strict models (fail-closed)."""
    model_cls = TOOL_ARG_MODELS.get(name)
    if model_cls is None:
        raise ValueError(f"unknown tool: {name}")
    parsed = model_cls.model_validate(raw)
    return parsed.model_dump()


__all__ = [
    "ConceptSearchArgs",
    "ConceptSyncArgs",
    "StoryListSourcesArgs",
    "StorySearchArgs",
    "StorySyncArgs",
    "TOOL_ARG_MODELS",
    "parse_tool_args",
]
