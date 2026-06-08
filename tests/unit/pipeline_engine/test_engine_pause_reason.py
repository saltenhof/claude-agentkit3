"""Unit tests for PauseReason typisierung and fail-closed InvalidPauseReasonError.

AK 5: unbekannter yield_status -> InvalidPauseReasonError (nicht PipelineError).
"""

from __future__ import annotations

import pytest

from agentkit.core_types import PauseReason
from agentkit.pipeline_engine.engine import _coerce_pause_reason
from agentkit.pipeline_engine.phase_envelope.errors import InvalidPauseReasonError


def test_coerce_pause_reason_none_returns_none() -> None:
    """None input -> None output (no pause reason set)."""
    assert _coerce_pause_reason(None, phase_name="setup") is None


def test_coerce_pause_reason_pause_reason_passthrough() -> None:
    """PauseReason input is returned unchanged."""
    pr = PauseReason.AWAITING_DESIGN_REVIEW
    result = _coerce_pause_reason(pr, phase_name="exploration")
    assert result is pr


def test_coerce_pause_reason_known_string_maps_correctly() -> None:
    """Known synonym strings are mapped to the correct PauseReason."""
    result = _coerce_pause_reason("awaiting_design_review", phase_name="exploration")
    assert result is PauseReason.AWAITING_DESIGN_REVIEW


def test_coerce_pause_reason_canonical_upper_case() -> None:
    """Canonical upper-case wire strings are accepted."""
    result = _coerce_pause_reason("GOVERNANCE_INCIDENT", phase_name="setup")
    assert result is PauseReason.GOVERNANCE_INCIDENT


def test_coerce_pause_reason_unknown_string_raises_invalid_pause_reason_error() -> None:
    """Unknown yield_status strings raise InvalidPauseReasonError (fail-closed, AK 5)."""
    with pytest.raises(InvalidPauseReasonError):
        _coerce_pause_reason("completely_unknown_status", phase_name="implementation")


def test_invalid_pause_reason_error_is_subclass_of_pipeline_error() -> None:
    """InvalidPauseReasonError is a subclass of PipelineError (type hierarchy)."""
    from agentkit.exceptions import PipelineError
    assert issubclass(InvalidPauseReasonError, PipelineError)


def test_coerce_pause_reason_empty_string_raises() -> None:
    """Empty string raises InvalidPauseReasonError (not a silent None)."""
    with pytest.raises(InvalidPauseReasonError):
        _coerce_pause_reason("", phase_name="setup")
