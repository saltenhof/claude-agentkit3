"""Authority classes and bundle entries for evidence assembly."""

from __future__ import annotations

from enum import IntEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

CONFIDENCE_PRIORITY: dict[str, int] = {
    "EXACT": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
}


class AuthorityClass(IntEnum):
    """Evidence authority classes ordered by review strength.

    Higher numeric values are more authoritative and are retained before lower
    classes when the evidence bundle exceeds the size limit.
    """

    WORKER_ASSERTION = 0
    SECONDARY_CONTEXT = 1
    PRIMARY_IMPLEMENTATION = 2
    PRIMARY_NORMATIVE = 3


class BundleEntry(BaseModel):
    """One file included in the review evidence bundle.

    Attributes:
        repo_id: Source repository identifier.
        path: File path relative to that repository root.
        authority: Evidence authority class.
        confidence: Optional import-resolution confidence label. Stage 1 and
            Stage 3 entries use ``None``.
        reason: Deterministic inclusion reason.
        size: UTF-8 byte size of ``content``.
        content: Loaded file content.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_id: str = Field(min_length=1)
    path: Path
    authority: AuthorityClass
    confidence: str | None = None
    reason: str = Field(min_length=1)
    size: int = Field(ge=0)
    content: str

    @field_validator("path")
    @classmethod
    def _path_must_be_relative(cls, value: Path) -> Path:
        """Reject absolute paths so manifest entries stay repo-scoped."""
        if value.is_absolute():
            msg = f"bundle entry path must be relative to repo root: {value}"
            raise ValueError(msg)
        if any(part == ".." for part in value.parts):
            msg = f"bundle entry path must not traverse outside repo root: {value}"
            raise ValueError(msg)
        return Path(value.as_posix())

    @property
    def sort_key(self) -> tuple[int, int, str, str]:
        """Return the deterministic keep-priority key for this entry.

        Sorting entries by this key keeps stronger authority first. Within one
        authority class, higher confidence wins, then repo and path stabilize
        the ordering.
        """
        confidence_rank = CONFIDENCE_PRIORITY.get(self.confidence or "", 0)
        return (-self.authority.value, -confidence_rank, self.repo_id, self.path.as_posix())


__all__ = ["AuthorityClass", "BundleEntry", "CONFIDENCE_PRIORITY"]
