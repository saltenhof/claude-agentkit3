"""Frozen data contracts for concept-authority prose evaluation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROMPT_VERSION = "authority-prose/v1"


class NormativeAssertion(BaseModel):
    """One normative assertion and the scopes it concerns."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion: str = Field(min_length=1)
    scopes: tuple[str, ...] = Field(min_length=1)

    @field_validator("assertion")
    @classmethod
    def assertion_must_be_non_empty(cls, value: str) -> str:
        """Reject whitespace-only evidence text."""
        if not value.strip():
            raise ValueError("assertion must be non-empty")
        return value

    @field_validator("scopes")
    @classmethod
    def scopes_must_be_non_empty(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Reject blank scope names fail closed."""
        if any(not value.strip() for value in values):
            raise ValueError("scope names must be non-empty")
        return values


class AuthorityProseResponse(BaseModel):
    """Strict structured response to the two W2 evaluation questions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    has_normative_statements: bool
    assertions: tuple[NormativeAssertion, ...]

    @model_validator(mode="after")
    def validate_consistency(self) -> AuthorityProseResponse:
        """Reject contradictory or incomplete classifications."""
        if self.has_normative_statements != bool(self.assertions):
            raise ValueError("has_normative_statements must match non-empty assertions")
        return self


class ChunkClassification(BaseModel):
    """Typed evaluator output consumed by deterministic policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    has_normative_statements: bool
    assertions: tuple[NormativeAssertion, ...]
    prompt_version: str
    prompt_sha256: str
    model: str


class AuthorityFinding(BaseModel):
    """Idempotently referenced W2 policy or run finding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    doc: str
    anchor: str
    assertion: str
    scope: str
    prompt_version: str
    model: str
    prompt_sha256: str = ""
    message: str
    severity: Literal["ERROR", "REPORT"] = "ERROR"
    baselined: bool = False

    @property
    def key(self) -> tuple[str, str, str, str, str, str, str]:
        """Return the stable baseline key fixed by AG3-159."""
        return (self.code, self.doc, self.anchor, self.assertion, self.scope, self.prompt_version, self.model)


class AuthorityRunResult(BaseModel):
    """Complete deterministic W2 result after baseline application."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: tuple[AuthorityFinding, ...]

    @property
    def ok(self) -> bool:
        """Return whether the run contains no active error."""
        return all(item.severity != "ERROR" for item in self.findings)
