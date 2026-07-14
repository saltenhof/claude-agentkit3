"""Strict justified baseline loading and keyed finding application."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

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

    @field_validator("reason")
    @classmethod
    def reason_must_be_non_empty(cls, value: str) -> str:
        """Reject missing-equivalent whitespace reasons."""
        if not value.strip():
            raise ValueError("every baseline entry requires a non-empty reason")
        return value

    @property
    def key(self) -> tuple[str, str, str, str, str, str, str]:
        """Return the exact idempotent finding key."""
        return (self.code, self.doc, self.anchor, self.assertion, self.scope, self.prompt_version, self.model)


class BaselineDocument(BaseModel):
    """Versioned W2 baseline document."""

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
