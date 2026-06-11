"""Consolidated story result axis (``terminal_state``) and ``exit_class``.

This module is the canonical owner (story-contracts BC, FK-59 §59.6/§59.8)
of the **consolidated result axis** of a Story and of the hard
validity/invalidity invariants between the result axes. It contains ONLY:

  - the result-axis type :class:`TerminalState` (``Open|Done|Cancelled``);
  - the ``exit_class`` type :class:`ExitClass` (official exit/split/reset
    subclasses, only legal under ``Cancelled``);
  - the single pure derivation :func:`derive_terminal_state`; and
  - the single fail-closed constraint :func:`validate_exit_class_constraints`.

Deliberate non-goals (owned elsewhere, FK-59 §59 / story AG3-074 §2.2):

  - It does NOT mutate Story status (``Done``/``Cancelled`` setting is owned
    by ``StoryService`` and the closure path).
  - It does NOT set / persist ``exit_class`` values (producers are AG3-072
    ``scope_split`` and AG3-073 ``viability_handoff``).
  - It does NOT introduce a second persistent status axis: ``terminal_state``
    is **derived** from the single ``StoryStatus`` owner
    (``story_model.py``), never stored as a rival field.

Distinction from ``StoryStatus`` (FK-59 §59.6.1, the central trap):
    ``StoryStatus`` (``Backlog|Approved|In Progress|Done|Cancelled``) is the
    GitHub/board wire status. ``terminal_state`` is the consolidated *result*
    view. ``Open`` is a **collector category** for every non-terminally-ended
    Story (Backlog/Approved/In Progress all map to ``Open``), NOT a separate
    administrative end-state.
"""

from __future__ import annotations

from enum import StrEnum

from agentkit.story_context_manager.story_model import StoryStatus


class TerminalState(StrEnum):
    """Consolidated story result axis (FK-59 §59.6.1).

    Exactly three values:

    Attributes:
        OPEN: Collector category for every Story that has not ended terminally
            (derived from ``Backlog``/``Approved``/``In Progress`` and any
            future non-terminal ``StoryStatus`` member). NOT an administrative
            end-state of its own.
        DONE: Successfully delivered (normal closure only, FK-59 §59.8 #4).
        CANCELLED: Administratively ended (story-exit/split/admin cancel);
            never the result of normal closure.
    """

    OPEN = "Open"
    DONE = "Done"
    CANCELLED = "Cancelled"


class ExitClass(StrEnum):
    """Official administrative exit subclass (FK-59 §59.6.2 / §59.11).

    ``exit_class`` is **not** a free-standing contract axis and **not** a free
    Story main field: it is only legal under ``terminal_state=Cancelled`` and
    is documented exclusively inside official exit/split/reset records. The
    member set is extensible for further official termination subclasses.

    Attributes:
        SCOPE_SPLIT: Outcome of a story split (FK-54; producer AG3-072).
        VIABILITY_HANDOFF: Outcome of a story exit / human-takeover handoff
            (FK-58; producer AG3-073).
    """

    SCOPE_SPLIT = "scope_split"
    VIABILITY_HANDOFF = "viability_handoff"


def derive_terminal_state(status: StoryStatus) -> TerminalState:
    """Derive the consolidated result axis from the single ``StoryStatus`` owner.

    Pure, total derivation (no I/O, no second persistent axis, FK-59 §59.6.1):

      - ``Done``      -> :attr:`TerminalState.DONE`
      - ``Cancelled`` -> :attr:`TerminalState.CANCELLED`
      - every other real ``StoryStatus`` member (``Backlog``/``Approved``/
        ``In Progress``) -> :attr:`TerminalState.OPEN`

    The mapping is exhaustive over the real ``StoryStatus`` members: the two
    terminal members are matched explicitly and **all** remaining members fall
    to ``Open``. This is deliberately written so that any *future* non-terminal
    ``StoryStatus`` member (e.g. a later ``RESETTING``/``RESET_FAILED`` that
    AG3-071 might add) automatically maps to ``Open`` without a change here —
    while still failing closed if ``StoryStatus`` ever gains a member that is
    not covered by the explicit terminal branches.

    Args:
        status: The authoritative wire/board status of the Story.

    Returns:
        The consolidated :class:`TerminalState` result view.
    """
    if status is StoryStatus.DONE:
        return TerminalState.DONE
    if status is StoryStatus.CANCELLED:
        return TerminalState.CANCELLED
    # Backlog / Approved / In Progress (and any future non-terminal member).
    return TerminalState.OPEN


def validate_exit_class_constraints(
    terminal_state: TerminalState,
    exit_class: ExitClass | None,
) -> None:
    """Fail-closed validation of the ``terminal_state``/``exit_class`` pairing.

    This is the single shared constraint owner (FK-59 §59.8 #2/#3) that the
    ``exit_class`` producers (AG3-072 ``scope_split`` / AG3-073
    ``viability_handoff``) consume. It enforces:

      - #2 ``terminal_state=Done`` + ``exit_class != None`` is illegal.
      - #3 ``terminal_state != Cancelled`` + ``exit_class != None`` is illegal
        (this subsumes #2 and also rejects ``Open`` + ``exit_class``).

    ``exit_class is None`` is always legal (``Open``/``Done``/``Cancelled``).
    ``Cancelled`` + any ``exit_class`` is legal.

    Args:
        terminal_state: The consolidated result axis value.
        exit_class: The official exit subclass, or ``None`` when absent.

    Raises:
        ValueError: When the combination is one of the hard FK-59 §59.8
            invalidities (#2/#3).
    """
    if exit_class is None:
        return
    if terminal_state is not TerminalState.CANCELLED:
        raise ValueError(
            "exit_class is only legal under terminal_state=Cancelled "
            f"(FK-59 §59.8 #2/#3); got terminal_state={terminal_state.value!r} "
            f"with exit_class={exit_class.value!r}",
        )


__all__ = [
    "ExitClass",
    "TerminalState",
    "derive_terminal_state",
    "validate_exit_class_constraints",
]
