"""Lifecycle transition tests for story_context_manager.

Tests the status graph exhaustively:
  - All valid transitions pass
  - All invalid transitions raise InvalidStatusTransitionError
  - Terminal statuses block further transitions
  - Special error message for In Progress -> Cancelled
"""

from __future__ import annotations

import pytest

from agentkit.backend.story_context_manager.errors import InvalidStatusTransitionError
from agentkit.backend.story_context_manager.service import (
    _check_transition,
    is_story_runnable_status,
)
from agentkit.backend.story_context_manager.story_model import StoryStatus

# All valid (from, to) transitions:
_VALID = [
    (StoryStatus.BACKLOG, StoryStatus.APPROVED),       # approve
    (StoryStatus.APPROVED, StoryStatus.BACKLOG),       # reject
    (StoryStatus.BACKLOG, StoryStatus.CANCELLED),      # cancel from backlog
    (StoryStatus.APPROVED, StoryStatus.CANCELLED),     # cancel from approved
    (StoryStatus.APPROVED, StoryStatus.IN_PROGRESS),   # begin_progress (pipeline)
    (StoryStatus.IN_PROGRESS, StoryStatus.DONE),       # complete_story (pipeline)
    # AG3-071 (FK-53) administrative reset axis:
    (StoryStatus.IN_PROGRESS, StoryStatus.RESETTING),    # begin_reset (fence)
    (StoryStatus.RESETTING, StoryStatus.IN_PROGRESS),    # complete_reset (restartable)
    (StoryStatus.RESETTING, StoryStatus.RESET_FAILED),   # mark_reset_failed
    (StoryStatus.RESET_FAILED, StoryStatus.RESETTING),   # resume_reset_transition
]

# All invalid (from, to) pairs that must raise (including same-status):
_ALL_STATUSES = list(StoryStatus)
_INVALID = [
    (f, t)
    for f in _ALL_STATUSES
    for t in _ALL_STATUSES
    if (f, t) not in _VALID  # same-status is also invalid (no idempotent bypass)
]


@pytest.mark.parametrize("from_status,to_status", _VALID)
def test_valid_transitions_do_not_raise(
    from_status: StoryStatus,
    to_status: StoryStatus,
) -> None:
    _check_transition(from_status, to_status)  # must not raise


@pytest.mark.parametrize("from_status,to_status", _INVALID)
def test_invalid_transitions_raise(
    from_status: StoryStatus,
    to_status: StoryStatus,
) -> None:
    with pytest.raises(InvalidStatusTransitionError):
        _check_transition(from_status, to_status)


def test_same_status_transition_is_rejected() -> None:
    """Same-status transitions must raise InvalidStatusTransitionError.

    Idempotent replay runs through the Idempotency-Layer (op_id),
    NOT through the status transition guard (Befund 4).
    """
    for status in StoryStatus:
        with pytest.raises(InvalidStatusTransitionError):
            _check_transition(status, status)


def test_in_progress_to_cancelled_has_informative_message() -> None:
    """Special case: In Progress -> Cancelled must mention story-reset."""
    with pytest.raises(InvalidStatusTransitionError, match="story-reset|FK-53"):
        _check_transition(StoryStatus.IN_PROGRESS, StoryStatus.CANCELLED)


def test_done_is_terminal_no_further_transitions() -> None:
    """Done -> anything (including Done itself) must raise."""
    terminal = StoryStatus.DONE
    for target in _ALL_STATUSES:
        with pytest.raises(InvalidStatusTransitionError):
            _check_transition(terminal, target)


def test_cancelled_is_terminal_no_further_transitions() -> None:
    """Cancelled -> anything (including Cancelled itself) must raise."""
    terminal = StoryStatus.CANCELLED
    for target in _ALL_STATUSES:
        with pytest.raises(InvalidStatusTransitionError):
            _check_transition(terminal, target)


def test_reset_axis_is_not_terminal() -> None:
    """RESETTING / RESET_FAILED are administrative, NOT terminal (FK-53 §53.8)."""
    from agentkit.backend.story_context_manager.service import _TERMINAL_STATUSES

    assert StoryStatus.RESETTING not in _TERMINAL_STATUSES
    assert StoryStatus.RESET_FAILED not in _TERMINAL_STATUSES


def test_reset_failed_is_not_runnable() -> None:
    """RESET_FAILED and RESETTING are NOT runnable (FK-53 §53.9.2, AC8)."""
    assert is_story_runnable_status(StoryStatus.RESET_FAILED) is False
    assert is_story_runnable_status(StoryStatus.RESETTING) is False


def test_normal_statuses_are_runnable() -> None:
    """Non-reset statuses remain runnable (the reset gate is the only blocker)."""
    for status in (
        StoryStatus.BACKLOG,
        StoryStatus.APPROVED,
        StoryStatus.IN_PROGRESS,
        StoryStatus.DONE,
        StoryStatus.CANCELLED,
    ):
        assert is_story_runnable_status(status) is True


def test_reset_does_not_reach_cancelled_from_in_progress() -> None:
    """The reset axis never sets Cancelled (counter-evidence to FK-91 drift, AC10)."""
    # The ONLY In Progress edges are DONE and RESETTING — never CANCELLED directly.
    with pytest.raises(InvalidStatusTransitionError):
        _check_transition(StoryStatus.IN_PROGRESS, StoryStatus.CANCELLED)
    with pytest.raises(InvalidStatusTransitionError):
        _check_transition(StoryStatus.RESETTING, StoryStatus.CANCELLED)
    with pytest.raises(InvalidStatusTransitionError):
        _check_transition(StoryStatus.RESET_FAILED, StoryStatus.CANCELLED)


def test_transition_error_carries_detail() -> None:
    """InvalidStatusTransitionError must have detail with current/target status."""
    with pytest.raises(InvalidStatusTransitionError) as exc_info:
        _check_transition(StoryStatus.DONE, StoryStatus.BACKLOG)

    detail = exc_info.value.detail
    assert "current_status" in detail
    assert "target_status" in detail
    assert detail["current_status"] == "Done"
    assert detail["target_status"] == "Backlog"
