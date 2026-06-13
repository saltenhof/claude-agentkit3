"""Tests for the cooldown mechanism (FK-35 §35.3.11).

Covers AC5 (same signal type blocked / other signal types unaffected).
"""

from __future__ import annotations

from datetime import UTC, datetime

from tests.unit.governance.governance_observer.conftest import ScriptedEventReader

from agentkit.governance.governance_observer.cooldown import should_adjudicate

_PROJECT_KEY = "PRJ"
_STORY_ID = "AG3-085"
_RUN_ID = "run-001"
_SIGNAL_A = "orchestrator_code_read_write"
_SIGNAL_B = "qa_fail_repeated"
_COOLDOWN_S = 300


def _recent_ts() -> float:
    """Return a timestamp 10 seconds ago (well within the cooldown window)."""
    return datetime.now(UTC).timestamp() - 10


def _old_ts() -> float:
    """Return a timestamp 400 seconds ago (past the cooldown window)."""
    return datetime.now(UTC).timestamp() - 400


def test_should_adjudicate_when_no_prior_adjudication() -> None:
    """should_adjudicate returns True when no prior adjudication exists (AC5)."""
    reader = ScriptedEventReader(last_adjudication_ts={})
    result = should_adjudicate(
        reader,
        _PROJECT_KEY,
        _STORY_ID,
        _RUN_ID,
        signal_type=_SIGNAL_A,
        cooldown_s=_COOLDOWN_S,
    )
    assert result is True


def test_same_signal_blocked_within_cooldown() -> None:
    """Same signal type is blocked when its last adjudication is recent (AC5)."""
    reader = ScriptedEventReader(last_adjudication_ts={_SIGNAL_A: _recent_ts()})
    result = should_adjudicate(
        reader,
        _PROJECT_KEY,
        _STORY_ID,
        _RUN_ID,
        signal_type=_SIGNAL_A,
        cooldown_s=_COOLDOWN_S,
    )
    assert result is False


def test_same_signal_allowed_after_cooldown_expired() -> None:
    """Same signal type is allowed after the cooldown window passes (AC5)."""
    reader = ScriptedEventReader(last_adjudication_ts={_SIGNAL_A: _old_ts()})
    result = should_adjudicate(
        reader,
        _PROJECT_KEY,
        _STORY_ID,
        _RUN_ID,
        signal_type=_SIGNAL_A,
        cooldown_s=_COOLDOWN_S,
    )
    assert result is True


def test_different_signal_type_unaffected_by_cooldown() -> None:
    """A different signal type is NOT blocked even when signal_a is in cooldown (AC5)."""
    reader = ScriptedEventReader(last_adjudication_ts={_SIGNAL_A: _recent_ts()})
    # Signal B has no recent adjudication -> should adjudicate
    result = should_adjudicate(
        reader,
        _PROJECT_KEY,
        _STORY_ID,
        _RUN_ID,
        signal_type=_SIGNAL_B,
        cooldown_s=_COOLDOWN_S,
    )
    assert result is True


def test_both_signals_blocked_when_both_recent() -> None:
    """Both signals are independently blocked when both have recent adjudications."""
    reader = ScriptedEventReader(
        last_adjudication_ts={
            _SIGNAL_A: _recent_ts(),
            _SIGNAL_B: _recent_ts(),
        }
    )
    assert not should_adjudicate(
        reader, _PROJECT_KEY, _STORY_ID, _RUN_ID, signal_type=_SIGNAL_A, cooldown_s=_COOLDOWN_S
    )
    assert not should_adjudicate(
        reader, _PROJECT_KEY, _STORY_ID, _RUN_ID, signal_type=_SIGNAL_B, cooldown_s=_COOLDOWN_S
    )
