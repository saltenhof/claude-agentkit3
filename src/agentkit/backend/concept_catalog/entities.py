"""Typed read representations for the concept catalog adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

ConceptLayer = Literal["domain", "technical", "formal"]


class ConceptRef(BaseModel):
    """Frontmatter-backed reference to one concept document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str
    path: Path
    layer: ConceptLayer
    title: str
    status: str
    domain: str | None = None
    tags: list[str]
    cross_cutting: bool
    defers_to: list[str]
    formal_refs: list[str]


class ConceptSearchHit(BaseModel):
    """Deterministic full-text search result for a concept document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str
    title: str
    snippet: str
    score: float


class ConceptBacklinks(BaseModel):
    """Incoming concept references for one concept document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str
    incoming_defers_to: list[str]
    incoming_formal_refs: list[str]
