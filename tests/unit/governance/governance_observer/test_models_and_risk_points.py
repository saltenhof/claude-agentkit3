"""Tests for GovernanceSignalType, RISK_POINTS, and IMMEDIATE_STOP_SIGNALS.

Covers AC2 (complete risk-points matrix), AC4 (immediate-stop signals), and
AC9 (unknown signal type -> hard reject).
"""

from __future__ import annotations

import pytest

from agentkit.governance.governance_observer.models import (
    IMMEDIATE_STOP_SIGNALS,
    RISK_POINTS,
    GovernanceSignalType,
)
from agentkit.governance.governance_observer.observer import (
    _parse_signal_type,
    lookup_risk_points,
)

# ---------------------------------------------------------------------------
# AC2 — complete risk-points matrix (FK-93 §93.6)
# ---------------------------------------------------------------------------

_EXPECTED_RISK_POINTS: dict[str, int] = {
    "orchestrator_code_read_write": 10,
    "orchestrator_bash_no_subagent": 8,
    "write_outside_story_scope": 8,
    "qa_fail_repeated": 15,
    "no_phase_progress": 12,
    "high_edit_revert_churn": 10,
    "subagent_repeated_failure": 12,
    "repeated_drifts": 15,
}


@pytest.mark.parametrize(
    ("wire_value", "expected_points"),
    list(_EXPECTED_RISK_POINTS.items()),
)
def test_risk_points_matrix_complete(wire_value: str, expected_points: int) -> None:
    """Every FK-93 §93.6 signal maps to the correct risk-point weight (AC2)."""
    signal = GovernanceSignalType(wire_value)
    assert RISK_POINTS[signal] == expected_points, (
        f"Signal {wire_value!r} expected {expected_points} pts, "
        f"got {RISK_POINTS[signal]}"
    )


def test_risk_points_map_contains_exactly_eight_scored_signals() -> None:
    """RISK_POINTS must contain exactly 8 scored signals (FK-93 §93.6)."""
    assert len(RISK_POINTS) == 8


def test_immediate_stop_signals_not_in_risk_points() -> None:
    """Immediate-stop signals must NOT appear in RISK_POINTS."""
    for sig in IMMEDIATE_STOP_SIGNALS:
        assert sig not in RISK_POINTS, (
            f"Immediate-stop signal {sig!r} must not have a point weight."
        )


def test_immediate_stop_signals_are_exactly_two() -> None:
    """IMMEDIATE_STOP_SIGNALS must contain exactly 2 members (FK-93 §93.6)."""
    assert len(IMMEDIATE_STOP_SIGNALS) == 2
    assert GovernanceSignalType.GOVERNANCE_FILE_MANIPULATION in IMMEDIATE_STOP_SIGNALS
    assert GovernanceSignalType.SECRET_ACCESS in IMMEDIATE_STOP_SIGNALS


# ---------------------------------------------------------------------------
# AC9 — unknown signal type -> hard reject (fail-closed)
# ---------------------------------------------------------------------------

def test_unknown_signal_type_raises_value_error() -> None:
    """An unrecognised signal type wire value must raise ValueError (AC9)."""
    with pytest.raises(ValueError, match="Unknown governance signal type"):
        _parse_signal_type("totally_unknown_signal_xyz")


def test_known_signal_type_parses_successfully() -> None:
    """A valid wire value must parse without error."""
    result = _parse_signal_type("orchestrator_code_read_write")
    assert result == GovernanceSignalType.ORCHESTRATOR_CODE_READ_WRITE


def test_lookup_risk_points_for_scored_signal() -> None:
    """lookup_risk_points returns the correct weight for a scored signal."""
    assert lookup_risk_points(GovernanceSignalType.QA_FAIL_REPEATED) == 15


def test_lookup_risk_points_for_immediate_stop_raises() -> None:
    """lookup_risk_points raises for immediate-stop signals (no point value)."""
    with pytest.raises(ValueError, match="immediate-stop signal"):
        lookup_risk_points(GovernanceSignalType.SECRET_ACCESS)
