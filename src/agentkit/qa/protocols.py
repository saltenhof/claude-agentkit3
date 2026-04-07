"""QA layer contracts -- defines what every QA layer must provide.

Central types for the 4-layer QA system. All result types are frozen
dataclasses (ARCH-29). Business results via return types, not
exceptions (ARCH-20).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story.models import StoryContext


class Severity(StrEnum):
    """Finding severity levels.

    Attributes:
        CRITICAL: Blocker -- must be fixed before progression.
        HIGH: Serious -- should be fixed before progression.
        MEDIUM: Relevant -- should be fixed if feasible.
        LOW: Note -- nice to fix.
        INFO: Informational -- no action required.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class TrustClass(StrEnum):
    """Trust classification for findings (ARCH-04: Single Source of Truth).

    System checks (A) are more trustworthy than worker assertions (C).

    Attributes:
        SYSTEM: Deterministic system check (build, lint, test).
        VERIFIED_LLM: LLM check with evidence verification.
        WORKER_ASSERTION: Worker self-report (least trusted).
    """

    SYSTEM = "A"
    VERIFIED_LLM = "B"
    WORKER_ASSERTION = "C"


@dataclass(frozen=True)
class Finding:
    """A single QA finding from any layer.

    Immutable value object. Domain concept, not a string (ARCH-14).

    Args:
        layer: Which layer produced this (e.g. ``"structural"``).
        check: Which specific check (e.g. ``"context_exists"``).
        severity: How severe the finding is.
        message: Human-readable description of the finding.
        trust_class: How trustworthy the source of this finding is.
        file_path: Optional file path related to the finding.
        line_number: Optional line number in the file.
        suggestion: Optional suggestion for remediation.
    """

    layer: str
    check: str
    severity: Severity
    message: str
    trust_class: TrustClass
    file_path: str | None = None
    line_number: int | None = None
    suggestion: str | None = None


@dataclass(frozen=True)
class LayerResult:
    """Result of a single QA layer evaluation.

    Fachliches Ergebnis via Return-Type, nicht Exception (ARCH-20).

    Args:
        layer: Name of the layer that produced this result.
        passed: Whether the layer evaluation passed overall.
        findings: Tuple of findings discovered during evaluation.
        metadata: Additional metadata about the evaluation.
    """

    layer: str
    passed: bool
    findings: tuple[Finding, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def critical_findings(self) -> tuple[Finding, ...]:
        """Return only CRITICAL severity findings.

        Returns:
            Tuple of findings with ``Severity.CRITICAL``.
        """
        return tuple(f for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def blocking_findings(self) -> tuple[Finding, ...]:
        """Return findings that block progression (CRITICAL or HIGH).

        Returns:
            Tuple of findings with ``Severity.CRITICAL`` or ``Severity.HIGH``.
        """
        return tuple(
            f for f in self.findings
            if f.severity in (Severity.CRITICAL, Severity.HIGH)
        )


@runtime_checkable
class QALayer(Protocol):
    """Contract for a QA layer (ARCH-06).

    Each layer evaluates one aspect of quality. Layers are:

    - Independent: can run without other layers.
    - Pure: no side effects during evaluation (ARCH-31).
    - Return-based: results via LayerResult, not exceptions (ARCH-20).
    """

    @property
    def name(self) -> str:
        """Layer identifier (e.g. ``"structural"``, ``"semantic"``).

        Returns:
            The name string for this layer.
        """
        ...

    def evaluate(self, ctx: StoryContext, story_dir: Path) -> LayerResult:
        """Evaluate this layer against a story's artifacts.

        Args:
            ctx: Story context for type/mode-specific evaluation.
            story_dir: Directory containing story artifacts.

        Returns:
            LayerResult with findings. Never raises for business errors.
        """
        ...
