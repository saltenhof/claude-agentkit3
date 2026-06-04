"""verify-system-specific exception hierarchy.

All exceptions in this module descend from ``VerifySystemError`` so that
callers can catch the entire BC's exception surface with a single
``except VerifySystemError`` clause if needed.

Quelle: AG3-026 §2.1.4 -- Fail-Closed-Wege.
"""

from __future__ import annotations


class VerifySystemError(Exception):
    """Base exception for all verify-system errors.

    All specialised exceptions in this BC inherit from this class,
    enabling broad catches at BC boundaries without obscuring intent.
    """


class VerifyTargetUnknownError(VerifySystemError):
    """Raised when the target_type cannot be resolved to a known VerifyTargetType.

    This is a fail-closed error: unknown target types are not tolerated
    silently (AG3-026 §2.1.4, FAIL-CLOSED guardrail).
    """


class LayerExecutionError(VerifySystemError):
    """Raised when a QA layer raises an unexpected exception during evaluate().

    The original exception is chained via ``raise LayerExecutionError(...) from exc``.
    The error is aggregated as a BLOCKING finding so that the policy engine
    can produce a definitive FAIL verdict (AG3-026 §2.1.4).
    """


class ResolutionMetadataError(VerifySystemError):
    """Raised when the Layer-2 finding-resolution metadata is malformed.

    Fail-closed (AG3-043 E5): the ``finding_resolutions`` metadata is produced
    by our own ``serialize_resolution_map`` and consumed by
    ``resolution_map_from_metadata``. A malformed structure (non-dict payload,
    a key that is not a well-formed ``"layer:check"`` pair, a non-string value,
    or an unknown status value) is therefore an internal pipeline corruption /
    bug, NOT external input. It is surfaced as a hard error rather than skipped
    silently (DK-04 §4.6 carries hard gate-effect through the existing
    architecture; FAIL-CLOSED guardrail).
    """


__all__ = [
    "LayerExecutionError",
    "ResolutionMetadataError",
    "VerifySystemError",
    "VerifyTargetUnknownError",
]
