"""Errors for the BC-9-hosted planning projection write path (FK-70 §70.10.2).

Owner-distinct pendants to the FK-69 accessor errors. They keep the planning
write boundary fail-closed (CLAUDE.md FAIL-CLOSED) without reusing or weakening
the FK-69 ``ProjectionRecordTypeMismatchError`` contract.
"""

from __future__ import annotations

from agentkit.exceptions import AgentKitError

__all__ = [
    "PlanningProjectionDeleteNotSupportedError",
    "PlanningProjectionRecordTypeMismatchError",
    "PlanningSchemaKindUnknownError",
]


class PlanningProjectionRecordTypeMismatchError(AgentKitError):
    """Raised when a record type does not match its ``PlanningSchemaKind``.

    Pendant to FK-69 ``ProjectionRecordTypeMismatchError`` for the planning
    write path. FAIL-CLOSED: a write with a mismatched record type is a
    programming/contract error and is rejected, never coerced.
    """

    def __init__(self, *, kind: object, expected: type, received: type) -> None:
        super().__init__(
            f"Planning record type mismatch for kind {kind!r}: "
            f"expected {expected.__name__}, received {received.__name__}",
            detail={
                "kind": str(kind),
                "expected": expected.__name__,
                "received": received.__name__,
            },
        )
        self.kind = kind
        self.expected = expected
        self.received = received


class PlanningProjectionDeleteNotSupportedError(AgentKitError):
    """Raised when ``delete_projection`` is called for a non-deletable family.

    FAIL-CLOSED: only the families whose adapter exposes a delete operation may
    be deleted through the single planning write boundary. Asking to delete a
    record from a family that has no delete semantics is a contract error, not a
    silent no-op.
    """

    def __init__(self, *, kind: object) -> None:
        super().__init__(
            f"Planning schema kind {kind!r} does not support delete_projection",
            detail={"kind": str(kind)},
        )
        self.kind = kind


class PlanningSchemaKindUnknownError(AgentKitError):
    """Raised when a ``PlanningSchemaKind`` has no registered repository/mapping.

    FAIL-CLOSED: an unmapped planning kind is a wiring defect, not a silent
    no-op.
    """

    def __init__(self, *, kind: object) -> None:
        super().__init__(
            f"No planning repository registered for kind {kind!r}",
            detail={"kind": str(kind)},
        )
        self.kind = kind
