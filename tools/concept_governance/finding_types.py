"""Shared finding identity and P4 triage value objects."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FindingLocus(BaseModel):
    """One stable document, anchor, and quoted-assertion locus."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    assertion: str = Field(min_length=1)

    @field_validator("doc", "anchor", "assertion")
    @classmethod
    def values_must_be_non_empty(cls, value: str) -> str:
        """Reject whitespace-only identity components."""
        if not value.strip():
            raise ValueError("finding locus values must be non-empty")
        return value


class FormalizationCheck(BaseModel):
    """Mandatory P4 triage decision with its concrete justification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    formalization_candidate: bool
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def reason_must_be_non_empty(cls, value: str) -> str:
        """Reject a P4 yes/no decision without a reason."""
        if not value.strip():
            raise ValueError("formalization check requires a non-empty reason")
        return value


def finding_key(
    code: str,
    primary: FindingLocus,
    related: tuple[FindingLocus, ...],
    scope: str,
    prompt_version: str,
    model: str,
) -> tuple[str, ...]:
    """Return the legacy-compatible key, extended only for related loci."""
    base = (code, primary.doc, primary.anchor, primary.assertion, scope, prompt_version, model)
    if not related:
        return base
    encoded = "\x1d".join("\x1e".join((item.doc, item.anchor, item.assertion)) for item in related)
    return (*base, encoded)
