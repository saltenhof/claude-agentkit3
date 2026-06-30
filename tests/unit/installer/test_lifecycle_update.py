"""Unit tests for the level-2 hybrid update driver (AG3-122, FK-10 §10.2.8)."""

from __future__ import annotations

import pytest

from agentkit.backend.installer.lifecycle.update import (
    REINSTALL_HINT,
    UpdateCompatError,
    UpdateStatus,
    evaluate_update,
)


def _window(*, minimum: str, recommended: str, blocked: tuple[str, ...] = ()) -> dict[str, object]:
    return {
        "agent_runtime": {
            "min": minimum,
            "max": "9.9.9",
            "recommended": recommended,
            "blocked": list(blocked),
        },
        "wire": {"min": "1", "max": "1", "recommended": "1", "blocked": []},
    }


def test_update_pass_when_at_or_above_recommended() -> None:
    decision = evaluate_update("1.2.0", _window(minimum="1.0.0", recommended="1.2.0"))
    assert decision.status is UpdateStatus.PASS
    assert decision.is_pass is True
    assert decision.reinstall_hint == REINSTALL_HINT


def test_update_warning_below_recommended_inside_window() -> None:
    decision = evaluate_update("1.1.0", _window(minimum="1.0.0", recommended="1.2.0"))
    assert decision.status is UpdateStatus.WARNING
    assert decision.is_pass is True
    # The §10.2.8 re-install hint accompanies a non-blocked update.
    assert decision.reinstall_hint == REINSTALL_HINT


def test_update_blocked_below_min_is_fail_closed() -> None:
    decision = evaluate_update("0.9.0", _window(minimum="1.0.0", recommended="1.2.0"))
    assert decision.status is UpdateStatus.BLOCKED
    assert decision.is_pass is False
    # A blocked update cannot proceed: no re-install hint is emitted.
    assert decision.reinstall_hint == ""
    assert "below the minimum" in decision.reason


def test_update_blocked_when_version_in_blocked_set() -> None:
    decision = evaluate_update(
        "1.1.0", _window(minimum="1.0.0", recommended="1.0.0", blocked=("1.1.0",))
    )
    assert decision.status is UpdateStatus.BLOCKED
    assert decision.is_pass is False
    assert "blocked set" in decision.reason


def test_update_blocked_matches_numeric_equal_notation() -> None:
    """B1 fail-OPEN regression: a semantically-equal version in a different notation
    must be BLOCKED, not slip past as PASS.

    ``"1.2"`` is numerically equal to the blocked ``"1.2.0"`` and to ``recommended``;
    the string-equality check that shipped returned PASS here (fail-open). The
    normalized numeric blocked check classifies it BLOCKED (fail-closed).
    """
    decision = evaluate_update(
        "1.2", _window(minimum="0.1.0", recommended="1.2.0", blocked=("1.2.0",))
    )
    assert decision.status is UpdateStatus.BLOCKED
    assert decision.is_pass is False
    assert "blocked set" in decision.reason


def test_update_blocked_exact_string_still_blocks() -> None:
    decision = evaluate_update(
        "1.2.0", _window(minimum="0.1.0", recommended="1.2.0", blocked=("1.2.0",))
    )
    assert decision.status is UpdateStatus.BLOCKED


def test_update_non_blocked_version_still_passes() -> None:
    decision = evaluate_update(
        "1.2.0", _window(minimum="0.1.0", recommended="1.2.0", blocked=("1.1.0",))
    )
    assert decision.status is UpdateStatus.PASS
    assert decision.is_pass is True


def test_update_unparsable_blocked_entry_is_skipped_safely() -> None:
    """A malformed blocked entry never crashes; a non-matching version still passes."""
    decision = evaluate_update(
        "1.3.0", _window(minimum="0.1.0", recommended="1.2.0", blocked=("garbage", "1.2.0"))
    )
    assert decision.status is UpdateStatus.PASS


def test_update_blocked_above_max_is_fail_closed() -> None:
    """D1 regression: a runtime ABOVE ``max`` must be BLOCKED, mirroring the server
    handshake (version_handshake._classify_runtime 426s an above-max runtime).

    The shipped driver ignored ``max`` and returned PASS, so ``agentkit update``
    said OK while the Core would 426 the very same runtime (inconsistent).
    """
    window = {
        "agent_runtime": {
            "min": "1.0.0",
            "max": "1.5.0",
            "recommended": "1.2.0",
            "blocked": [],
        },
        "wire": {"min": "1", "max": "1", "recommended": "1", "blocked": []},
    }
    decision = evaluate_update("1.6.0", window)
    assert decision.status is UpdateStatus.BLOCKED
    assert decision.is_pass is False
    assert decision.reinstall_hint == ""
    assert "above the maximum" in decision.reason
    assert decision.max_version == "1.5.0"


def test_update_at_max_still_passes() -> None:
    """A runtime exactly at ``max`` (and >= recommended) is PASS, not blocked."""
    window = {
        "agent_runtime": {
            "min": "1.0.0",
            "max": "1.5.0",
            "recommended": "1.2.0",
            "blocked": [],
        },
        "wire": {"min": "1", "max": "1", "recommended": "1", "blocked": []},
    }
    decision = evaluate_update("1.5.0", window)
    assert decision.status is UpdateStatus.PASS


def test_update_missing_max_fails_closed() -> None:
    """D1: ``max`` is required (the server announces it); a window without it is
    malformed and must fail closed, not be treated as PASS."""
    window = {
        "agent_runtime": {"min": "1.0.0", "recommended": "1.2.0", "blocked": []},
        "wire": {"min": "1", "max": "1", "recommended": "1", "blocked": []},
    }
    with pytest.raises(UpdateCompatError):
        evaluate_update("1.3.0", window)


def test_update_malformed_max_fails_closed() -> None:
    """D1: an unparsable ``max`` is a malformed window (fail-closed)."""
    window = {
        "agent_runtime": {
            "min": "1.0.0",
            "max": "not-a-version",
            "recommended": "1.2.0",
            "blocked": [],
        },
        "wire": {"min": "1", "max": "1", "recommended": "1", "blocked": []},
    }
    with pytest.raises(UpdateCompatError):
        evaluate_update("1.3.0", window)


def test_update_malformed_wire_axis_fails_closed() -> None:
    """D1: the ``wire`` axis is a handshake participant the server announces; a
    malformed wire axis (unparsable ``max``) means an untrustworthy window and
    must fail closed rather than be ignored."""
    window = {
        "agent_runtime": {
            "min": "1.0.0",
            "max": "9.9.9",
            "recommended": "1.2.0",
            "blocked": [],
        },
        "wire": {"min": "1", "max": "garbage", "recommended": "1", "blocked": []},
    }
    with pytest.raises(UpdateCompatError):
        evaluate_update("1.3.0", window)


def test_update_missing_wire_axis_fails_closed() -> None:
    """D1: a window missing the ``wire`` axis entirely is malformed (fail-closed)."""
    window = {
        "agent_runtime": {
            "min": "1.0.0",
            "max": "9.9.9",
            "recommended": "1.2.0",
            "blocked": [],
        },
    }
    with pytest.raises(UpdateCompatError):
        evaluate_update("1.3.0", window)


def test_update_malformed_window_fails_closed() -> None:
    with pytest.raises(UpdateCompatError):
        evaluate_update("1.0.0", {"wire": {}})


def test_update_unparsable_local_version_fails_closed() -> None:
    with pytest.raises(UpdateCompatError):
        evaluate_update("not-a-version", _window(minimum="1.0.0", recommended="1.0.0"))
