"""Strict justified baseline loading and keyed finding application."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from concept_governance.finding_types import FindingLocus, FormalizationCheck, finding_key

if TYPE_CHECKING:
    from pathlib import Path


class BaselineEntry(BaseModel):
    """One exact finding key with a mandatory specific reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    code: str
    doc: str
    anchor: str
    assertion: str
    scope: str
    prompt_version: str
    model: str
    reason: str
    related_loci: tuple[FindingLocus, ...] = ()
    formalization_check: FormalizationCheck | None = None

    @field_validator("reason")
    @classmethod
    def reason_must_be_non_empty(cls, value: str) -> str:
        """Reject missing-equivalent whitespace reasons."""
        if not value.strip():
            raise ValueError("every baseline entry requires a non-empty reason")
        return value

    @model_validator(mode="after")
    def validate_scope_consistency_triage(self) -> BaselineEntry:
        """Require both loci and the P4 decision for every W3 contradiction."""
        if self.code == "SCOPE_CONTRADICTION":
            if not self.related_loci:
                raise ValueError("scope contradiction baseline entries require related_loci")
            if self.formalization_check is None:
                raise ValueError("scope contradiction baseline entries require formalization_check")
        return self

    @property
    def key(self) -> tuple[str, ...]:
        """Return the exact idempotent finding key."""
        primary = FindingLocus(doc=self.doc, anchor=self.anchor, assertion=self.assertion)
        return finding_key(
            self.code, primary, self.related_loci, self.scope, self.prompt_version, self.model
        )


class BaselineDocument(BaseModel):
    """Versioned shared W2/W3 governance baseline document."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal[1]
    entries: tuple[BaselineEntry, ...]

    @model_validator(mode="after")
    def keys_must_be_unique(self) -> BaselineDocument:
        """Reject duplicate suppression keys."""
        keys = [entry.key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("baseline entries must have unique finding keys")
        return self


class BaselineError(ValueError):
    """Raised when the baseline cannot be trusted."""


def load_baseline(path: Path) -> BaselineDocument:
    """Load a version-1 justified baseline or fail closed."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        return BaselineDocument.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise BaselineError(str(exc)) from exc
