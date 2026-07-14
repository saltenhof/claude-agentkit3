"""Frozen deterministic contracts for W3 scope sets and findings."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from concept_governance.finding_types import FindingLocus, FormalizationCheck, finding_key

SCOPE_PROMPT_VERSION = "scope-consistency/v1"
_PARTITION_NAMESPACE = uuid.UUID("28ab3405-6260-56e0-aac0-917ef26e601d")
class ScopeAssertionChunk(BaseModel):
    """One complete deterministic discovery chunk in a scope set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(min_length=1)
    doc: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    text: str = Field(min_length=1)
class ScopeSet(BaseModel):
    """All candidate assertion chunks authorized for one live scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: str = Field(min_length=1)
    assertions: tuple[ScopeAssertionChunk, ...]

    @model_validator(mode="after")
    def chunk_ids_must_be_unique(self) -> ScopeSet:
        """Reject duplicate discovery chunks in a closed set."""
        ids = [item.chunk_id for item in self.assertions]
        if len(ids) != len(set(ids)):
            raise ValueError("scope set chunk IDs must be unique")
        return self


class ScopePartition(BaseModel):
    """One stable, non-truncated partition of a scope set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: str = Field(min_length=1)
    index: int = Field(ge=1)
    count: int = Field(ge=1)
    assertions: tuple[ScopeAssertionChunk, ...] = Field(min_length=1)

    @property
    def partition_id(self) -> str:
        """Return a stable routing and checkpoint identity."""
        ids = "\x1f".join(item.chunk_id for item in self.assertions)
        return str(uuid.uuid5(_PARTITION_NAMESPACE, f"{self.scope}\x1f{self.index}\x1f{ids}"))


class ScopeConsistencyFinding(BaseModel):
    """One deterministic W3 policy or operational finding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    doc: str
    anchor: str
    assertion: str
    related_loci: tuple[FindingLocus, ...]
    scope: str
    prompt_version: str
    model: str
    prompt_sha256: str = ""
    message: str
    formalization_check: FormalizationCheck | None
    severity: Literal["ERROR", "REPORT"] = "ERROR"
    baselined: bool = False

    @property
    def key(self) -> tuple[str, ...]:
        """Return the shared-baseline identity including every locus."""
        primary = FindingLocus(doc=self.doc, anchor=self.anchor, assertion=self.assertion)
        return finding_key(
            self.code, primary, self.related_loci, self.scope, self.prompt_version, self.model
        )


class ScopeConsistencyRunResult(BaseModel):
    """Complete W3 result after all partitions and baseline policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: tuple[ScopeConsistencyFinding, ...]
    scope_sets: int = Field(ge=0)
    partitions: int = Field(ge=0)
    completed_partitions: int = Field(ge=0)

    @property
    def ok(self) -> bool:
        """Return whether no active error remains."""
        return all(item.severity != "ERROR" for item in self.findings)
