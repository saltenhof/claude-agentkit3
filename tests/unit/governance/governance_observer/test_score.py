"""Tests for rolling-window score computation (FK-35 §35.3.1a / §35.3.5).

Covers AC1 (rolling window query), AC6 (window eviction), AC2/AC9 fail-closed
payload validation, and proves that no in-memory state carries the score
between calls (AC1 anti-state test).
"""

from __future__ import annotations

import pytest
from tests.unit.governance.governance_observer.conftest import ScriptedEventReader

from agentkit.governance.governance_observer.score import (
    GovernanceSignalPayloadError,
    compute_risk_score,
)
from agentkit.telemetry.events import EventPayloadContractError

# ---------------------------------------------------------------------------
# AC1 — rolling-window score accumulation
# ---------------------------------------------------------------------------

def test_score_is_sum_of_risk_points_in_window() -> None:
    """Score equals sum of risk_points from the most-recent window events (AC1)."""
    payloads = [
        {"risk_points": 10, "signal_type": "orchestrator_code_read_write", "actor": "agent"},
        {"risk_points": 8, "signal_type": "orchestrator_bash_no_subagent", "actor": "agent"},
        {"risk_points": 15, "signal_type": "qa_fail_repeated", "actor": "agent"},
    ]
    reader = ScriptedEventReader(signal_payloads=payloads)
    score = compute_risk_score(reader, "PRJ", "AG3-085", "run-001", window_size=50)
    assert score == 33


def test_score_is_zero_for_empty_window() -> None:
    """Score is 0 when there are no events in the window."""
    reader = ScriptedEventReader(signal_payloads=[])
    score = compute_risk_score(reader, "PRJ", "AG3-085", "run-001", window_size=50)
    assert score == 0


def test_score_uses_limit_from_window_size() -> None:
    """The reader is called with the exact window_size as the limit (AC1)."""
    reader = ScriptedEventReader(
        signal_payloads=[
            {"risk_points": 5, "signal_type": "orchestrator_code_read_write", "actor": "agent"}
        ]
    )
    compute_risk_score(reader, "PRJ", "AG3-085", "run-001", window_size=50)
    assert reader.read_calls[0]["limit"] == 50


# ---------------------------------------------------------------------------
# AC6 — rolling-window eviction (events beyond window_size fall out of LIMIT)
# ---------------------------------------------------------------------------

def test_window_eviction_events_beyond_limit_excluded() -> None:
    """Events beyond window_size fall out of the LIMIT query (AC6).

    The reader returns only up to ``limit`` payloads; older events are not
    included.  This verifies the DESC LIMIT semantics: 5 events exist but
    window_size=3 so only the 3 newest contribute.
    """
    _valid = {"signal_type": "orchestrator_code_read_write", "actor": "agent"}
    all_payloads = [
        {"risk_points": 10, **_valid},
        {"risk_points": 10, **_valid},
        {"risk_points": 10, **_valid},
        {"risk_points": 99, **_valid},  # This WOULD push the score way up ...
        {"risk_points": 99, **_valid},  # ... but it's beyond window_size=3
    ]
    reader = ScriptedEventReader(signal_payloads=all_payloads)
    score = compute_risk_score(reader, "PRJ", "AG3-085", "run-001", window_size=3)
    # Only first 3 are returned by the reader (simulate LIMIT 3)
    assert score == 30  # 10+10+10


def test_window_size_limits_reader_call() -> None:
    """The reader is always called with the window_size as the limit."""
    reader = ScriptedEventReader(
        signal_payloads=[
            {"risk_points": 5, "signal_type": "orchestrator_code_read_write", "actor": "agent"}
        ]
    )
    compute_risk_score(reader, "PRJ", "AG3-085", "run-001", window_size=7)
    assert reader.read_calls[0]["limit"] == 7


# ---------------------------------------------------------------------------
# AC1 anti-state — no in-memory state between calls
# ---------------------------------------------------------------------------

def test_no_in_memory_state_between_calls() -> None:
    """Score reflects ONLY the reader's current data — no process-internal state.

    Two successive calls with different reader payloads must yield different
    scores, proving the score is computed fresh each time (no cached/accumulated
    in-memory state between calls).
    """
    _valid = {"signal_type": "orchestrator_code_read_write", "actor": "agent"}
    reader_a = ScriptedEventReader(signal_payloads=[{"risk_points": 10, **_valid}])
    reader_b = ScriptedEventReader(signal_payloads=[{"risk_points": 20, **_valid}])

    score_a = compute_risk_score(reader_a, "PRJ", "AG3-085", "run-001", window_size=50)
    score_b = compute_risk_score(reader_b, "PRJ", "AG3-085", "run-001", window_size=50)

    assert score_a == 10
    assert score_b == 20
    # Verify independence: scores are not cumulative (each reader is fresh)
    assert score_a + score_b == 30  # 10 + 20, NOT 10 + (10+20)


# ---------------------------------------------------------------------------
# AC2/AC9 — fail-closed payload validation (replaces bypass test)
# ---------------------------------------------------------------------------


def test_missing_risk_points_raises_fail_closed() -> None:
    """A payload missing ``risk_points`` raises fail-closed (AC2/AC9).

    The old behaviour silently coerced missing risk_points to 0.  FAIL-CLOSED
    contract: a missing mandatory field is a DATA INTEGRITY VIOLATION — it must
    raise, not silently lower the score.
    """
    payloads = [
        {"signal_type": "orchestrator_code_read_write", "actor": "agent"},  # missing risk_points
    ]
    reader = ScriptedEventReader(signal_payloads=payloads)
    with pytest.raises(EventPayloadContractError):
        compute_risk_score(reader, "PRJ", "AG3-085", "run-001", window_size=50)


def test_non_int_risk_points_raises_fail_closed() -> None:
    """A payload with a non-int ``risk_points`` raises fail-closed (AC2/AC9).

    String / float / None ``risk_points`` is a data-integrity violation and
    must not silently coerce to 0.
    """
    payloads = [
        {
            "risk_points": "not_an_int",
            "signal_type": "orchestrator_code_read_write",
            "actor": "agent",
        }
    ]
    reader = ScriptedEventReader(signal_payloads=payloads)
    with pytest.raises(GovernanceSignalPayloadError):
        compute_risk_score(reader, "PRJ", "AG3-085", "run-001", window_size=50)


def test_unknown_signal_type_raises_fail_closed() -> None:
    """An unknown ``signal_type`` raises fail-closed (AC2/AC9).

    A stored row with an unrecognised signal_type is a data-integrity
    violation — no silent default, no skip, no zero-point coercion.
    """
    payloads = [
        {"risk_points": 10, "signal_type": "totally_unknown_signal", "actor": "agent"}
    ]
    reader = ScriptedEventReader(signal_payloads=payloads)
    with pytest.raises(GovernanceSignalPayloadError):
        compute_risk_score(reader, "PRJ", "AG3-085", "run-001", window_size=50)


def test_immediate_stop_signal_as_scored_row_raises_fail_closed() -> None:
    """An immediate-stop signal in the scoring window raises fail-closed (AC2/AC9).

    Immediate-stop signals (GOVERNANCE_FILE_MANIPULATION / SECRET_ACCESS) have
    NO risk_points and bypass the rolling-window accumulator.  A stored row with
    one of these signal types in the scoring window is a contract violation.
    """
    payloads = [
        {"risk_points": 10, "signal_type": "governance_file_manipulation", "actor": "agent"}
    ]
    reader = ScriptedEventReader(signal_payloads=payloads)
    with pytest.raises(GovernanceSignalPayloadError):
        compute_risk_score(reader, "PRJ", "AG3-085", "run-001", window_size=50)


def test_missing_mandatory_actor_raises_fail_closed() -> None:
    """A payload missing the mandatory ``actor`` field raises fail-closed (AC2/AC9)."""
    payloads = [
        {"risk_points": 10, "signal_type": "orchestrator_code_read_write"}
        # missing: actor
    ]
    reader = ScriptedEventReader(signal_payloads=payloads)
    with pytest.raises(EventPayloadContractError):
        compute_risk_score(reader, "PRJ", "AG3-085", "run-001", window_size=50)
