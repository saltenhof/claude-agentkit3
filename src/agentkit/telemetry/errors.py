"""Telemetry domain errors.

Defines exception types raised by the telemetry BC.
"""

from __future__ import annotations

__all__ = ("ProjectionRecordTypeMismatchError",)


class ProjectionRecordTypeMismatchError(TypeError):
    """Raised when a ``ProjectionRecord`` type does not match the expected ``ProjectionKind``.

    Per FK-69 §69.4 (Schreib-Ownership): each ProjectionKind maps to exactly
    one Record type. Passing the wrong record type is a programming error
    (FAIL-CLOSED: raise, never silently coerce).

    Args:
        kind: The ``ProjectionKind`` that was requested.
        expected: The Python type expected for that kind.
        received: The Python type actually passed.
    """

    def __init__(
        self,
        kind: object,
        expected: type,
        received: type,
    ) -> None:
        super().__init__(
            f"ProjectionKind {kind!r} expects record type {expected.__name__!r}, "
            f"got {received.__name__!r}. "
            "FAIL-CLOSED: each ProjectionKind accepts exactly one record type "
            "(FK-69 §69.4)."
        )
        self.kind = kind
        self.expected = expected
        self.received = received
