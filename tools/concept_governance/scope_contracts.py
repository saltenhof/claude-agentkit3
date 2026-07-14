"""Strict structured-response contracts for the W3 evaluator."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QuotedAssertion(BaseModel):
    """One evaluator-reported exact quote and stable input locus."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(min_length=1)
    doc: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    assertion: str = Field(min_length=1)

    @field_validator("chunk_id", "doc", "anchor", "assertion")
    @classmethod
    def values_must_be_non_empty(cls, value: str) -> str:
        """Reject whitespace-only response evidence."""
        if not value.strip():
            raise ValueError("quoted assertion fields must be non-empty")
        return value


class ContradictionGroup(BaseModel):
    """Two or more reported, mutually contradictory assertions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    loci: tuple[QuotedAssertion, ...] = Field(min_length=2)
    explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def loci_must_be_distinct(self) -> ContradictionGroup:
        """Reject repeated copies of one quoted assertion."""
        identities = [(item.chunk_id, item.assertion) for item in self.loci]
        if len(identities) != len(set(identities)):
            raise ValueError("contradiction group loci must be distinct")
        return self


class ScopeConsistencyResponse(BaseModel):
    """LLM classification input to policy, deliberately without verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contradictions: tuple[ContradictionGroup, ...]


class ScopeEvaluation(BaseModel):
    """Parsed response with pinned prompt and resolved model identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    response: ScopeConsistencyResponse
    prompt_version: str
    prompt_sha256: str
    model: str
