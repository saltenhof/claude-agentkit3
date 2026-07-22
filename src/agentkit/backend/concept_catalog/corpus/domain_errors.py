"""Typed errors for the transport-free concept domain kernel."""

from __future__ import annotations


class ConceptDomainError(Exception):
    """Base error for the concepts domain package."""


class ConceptParseError(ConceptDomainError):
    """Raised when a concept source fails strict parse (fail-closed)."""

    def __init__(self, code: str, message: str, *, path: str | None = None) -> None:
        self.code = code
        self.path = path
        prefix = f"{code}: "
        if path:
            prefix = f"{code} ({path}): "
        super().__init__(prefix + message)


class ConceptValidationError(ConceptDomainError):
    """Raised when corpus validation finds blocking errors."""

    def __init__(self, message: str, *, findings: tuple[object, ...] = ()) -> None:
        self.findings = findings
        super().__init__(message)


__all__ = [
    "ConceptDomainError",
    "ConceptParseError",
    "ConceptValidationError",
]
