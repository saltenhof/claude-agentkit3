"""Governance contracts -- what every guard must provide.

Defines the ``GovernanceGuard`` protocol (ARCH-06), the ``GuardVerdict``
result type (ARCH-29 frozen, ARCH-20 return-based), and the
``ViolationType`` domain enum (ARCH-14).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ViolationType(StrEnum):
    """Types of governance violations (ARCH-14).

    Each value names a distinct category of policy breach that the
    governance system can detect and report.
    """

    BRANCH_VIOLATION = "branch_violation"
    SCOPE_VIOLATION = "scope_violation"
    ARTIFACT_TAMPERING = "artifact_tampering"
    UNAUTHORIZED_OPERATION = "unauthorized_operation"
    INTEGRITY_FAILURE = "integrity_failure"
    POLICY_VIOLATION = "policy_violation"


@dataclass(frozen=True)
class GuardVerdict:
    """Result of a governance guard evaluation. Immutable (ARCH-29).

    Attributes:
        allowed: Whether the evaluated operation is permitted.
        guard_name: Identifier of the guard that produced this verdict.
        violation_type: Category of violation (``None`` when allowed).
        message: Human-readable explanation (typically set on block).
        detail: Structured detail dict for audit logging.
    """

    allowed: bool
    guard_name: str
    violation_type: ViolationType | None = None
    message: str | None = None
    detail: dict[str, object] | None = None

    @classmethod
    def allow(cls, guard_name: str) -> GuardVerdict:
        """Create a verdict that permits the operation.

        Args:
            guard_name: Identifier of the guard issuing the verdict.

        Returns:
            A ``GuardVerdict`` with ``allowed=True``.
        """
        return cls(allowed=True, guard_name=guard_name)

    @classmethod
    def block(
        cls,
        guard_name: str,
        violation_type: ViolationType,
        message: str,
        detail: dict[str, object] | None = None,
    ) -> GuardVerdict:
        """Create a verdict that blocks the operation.

        Args:
            guard_name: Identifier of the guard issuing the verdict.
            violation_type: Category of the detected violation.
            message: Human-readable explanation of the block.
            detail: Optional structured data for audit logging.

        Returns:
            A ``GuardVerdict`` with ``allowed=False``.
        """
        return cls(
            allowed=False,
            guard_name=guard_name,
            violation_type=violation_type,
            message=message,
            detail=detail,
        )


class GovernanceGuard(Protocol):
    """Contract for a governance guard (ARCH-06).

    Guards are:
    - **Fast**: No LLM calls, no HTTP, no heavy I/O.
    - **Deterministic**: Same input produces same output.
    - **Independent**: Can run without other guards (ARCH-33).
    - **Return-based**: Results via ``GuardVerdict``, not exceptions (ARCH-20).
    """

    @property
    def name(self) -> str:
        """Short identifier for this guard."""
        ...

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        """Evaluate whether an operation is allowed.

        Args:
            operation: What is being attempted (e.g. ``"git_push"``,
                ``"write_qa_artifact"``).
            context: Operation context (file paths, commands, story state).

        Returns:
            A ``GuardVerdict`` indicating permission or denial.
        """
        ...
