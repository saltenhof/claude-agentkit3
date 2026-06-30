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


def test_update_malformed_window_fails_closed() -> None:
    with pytest.raises(UpdateCompatError):
        evaluate_update("1.0.0", {"wire": {}})


def test_update_unparsable_local_version_fails_closed() -> None:
    with pytest.raises(UpdateCompatError):
        evaluate_update("not-a-version", _window(minimum="1.0.0", recommended="1.0.0"))
