"""Telemetry domain errors.

Defines exception types raised by the telemetry BC.
"""

from __future__ import annotations

__all__ = (
    "ProjectionKindNotAccessorOwnedError",
    "ProjectionRecordTypeMismatchError",
)


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


class ProjectionKindNotAccessorOwnedError(NotImplementedError):
    """Raised when write/read targets a ``ProjectionKind`` the accessor does not own.

    FK-69 §69.3 lists all 7 read-model tables; §69.4 assigns write-ownership.
    The ``ProjectionAccessor`` owns the write/read path only for the QA and
    ``story_metrics`` kinds in AG3-035. ``phase_state_projection`` is written by
    ``pipeline_engine.PhaseExecutor`` (FK-69 §69.4); the ``fc_*`` tables are
    owned by AG3-028 (FailureCorpus). This is an explicit, fail-closed contract
    boundary -- NOT a half-built path. The enum value is intentionally published
    (FK-69 §69.3 demands the full 7), but the accessor refuses the operation and
    names the responsible owner instead of silently degrading.

    Subclasses :class:`NotImplementedError` so callers guarding the deferred
    paths keep working, while the dedicated type carries the ``kind``/``owner``
    semantics for honest assertions.

    Args:
        kind: The ``ProjectionKind`` whose data path is owned elsewhere.
        owner: Human-readable description of the owning writer/story.
    """

    def __init__(self, kind: object, owner: str) -> None:
        super().__init__(
            f"ProjectionKind {kind!r} is not owned by ProjectionAccessor. "
            f"Owner: {owner}. FAIL-CLOSED: the accessor refuses write/read for "
            "externally-owned FK-69 kinds (FK-69 §69.3/§69.4) instead of "
            "exposing a half-built path."
        )
        self.kind = kind
        self.owner = owner
