"""Typed reviewer request DSL for preflight evidence enrichment."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RequestType(StrEnum):
    """Structured reviewer request types supported by the preflight turn."""

    NEED_FILE = "NEED_FILE"
    NEED_SCHEMA = "NEED_SCHEMA"
    NEED_CALLSITE = "NEED_CALLSITE"
    NEED_RUNTIME_BINDING = "NEED_RUNTIME_BINDING"
    NEED_TEST_EVIDENCE = "NEED_TEST_EVIDENCE"
    NEED_CONCEPT_SOURCE = "NEED_CONCEPT_SOURCE"
    NEED_DIFF_EXPANSION = "NEED_DIFF_EXPANSION"


class ReviewerRequest(BaseModel):
    """One structured request emitted by a reviewer during preflight."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: RequestType
    target: str = Field(min_length=1, description="Path, symbol, pattern or command")
    region: str | None = Field(default=None, description="Region for NEED_DIFF_EXPANSION")
    reason: str = Field(min_length=1, description="Why this information is needed")


class RequestResult(BaseModel):
    """Deterministic resolution result for one reviewer request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request: ReviewerRequest
    status: str = Field(description="RESOLVED | UNRESOLVED | TIMEOUT | ERROR")
    content: str | None = None
    file_path: str | None = None
    duration_ms: int = 0


__all__ = ["RequestResult", "RequestType", "ReviewerRequest"]
