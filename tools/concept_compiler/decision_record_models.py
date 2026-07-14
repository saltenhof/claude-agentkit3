"""Value objects for the deterministic concept decision-record gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ChangeKind = Literal["A", "M", "D", "R"]


class ChangedBodyLine(BaseModel):
    """One added or removed Markdown body line."""

    model_config = ConfigDict(frozen=True)

    line: int = Field(ge=1)
    text: str


class ConceptFileChange(BaseModel):
    """One changed repository file with already-separated body lines."""

    model_config = ConfigDict(frozen=True)

    path: str
    change_kind: ChangeKind
    post_path: str | None = None
    added_body_lines: tuple[ChangedBodyLine, ...] = ()
    removed_body_lines: tuple[ChangedBodyLine, ...] = ()

    @property
    def body_lines(self) -> tuple[ChangedBodyLine, ...]:
        """Return all changed body lines in deterministic order."""
        return tuple(sorted((*self.added_body_lines, *self.removed_body_lines), key=lambda item: item.line))


class ConceptDiff(BaseModel):
    """Injected, git-free value object evaluated by the compliance core."""

    model_config = ConfigDict(frozen=True)

    changed_files: tuple[ConceptFileChange, ...]
    record_files: frozenset[str] = frozenset()
    schema_conform_record_files: frozenset[str] = frozenset()


@dataclass(frozen=True, order=True)
class DecisionRecordFinding:
    """One deterministic blocking decision-record finding."""

    path: str
    line: int
    code: str
    message: str
    severity: str = "ERROR"


@dataclass(frozen=True)
class DecisionRecordResult:
    """Stable findings produced by the compliance evaluation."""

    findings: tuple[DecisionRecordFinding, ...]

    @property
    def ok(self) -> bool:
        """Return whether the range is compliant."""
        return not self.findings
