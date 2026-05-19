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


__all__ = [
    "LayerExecutionError",
    "VerifySystemError",
    "VerifyTargetUnknownError",
]
