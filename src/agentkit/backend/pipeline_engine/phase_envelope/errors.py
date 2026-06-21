"""Typed exceptions for the phase_envelope sub.

InvalidPauseReasonError is the fail-closed alternative to the generic
PipelineError fallback that was used in _coerce_pause_reason before
AG3-024. It provides a narrower type for callers that need to distinguish
unknown-yield-status failures from other pipeline errors.
"""

from __future__ import annotations

from agentkit.backend.exceptions import PipelineError


class InvalidPauseReasonError(PipelineError):
    """Handler produced a yield_status that does not map to a PauseReason.

    Fail-closed: unrecognised yield_status strings are never silently
    coerced to a default. The handler contract (FK-39 §39.2.2) allows
    exactly three PauseReason values; anything else is an error.
    """
