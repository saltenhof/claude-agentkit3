"""Unit tests for the consolidated story result axis (AG3-074, FK-59).

Covers the axis types, the pure derivation, the fail-closed constraint
function and the six §59.12 mandated invariant tests. All assertions run
against real production code (no skip, no stub).

AC mapping (story.md §3):
  - AK1: derivation + exhaustiveness (no else hole).
  - AK2: Story/contract model carries no exit_class field.
  - AK3 (#2): Done + exit_class -> raise.
  - AK4 (#3): != Cancelled + exit_class -> raise; positives never raise.
  - AK6: the six §59.12 named tests.
  - AK7: the constraint function directly (positive + #2/#3 negative).
  - AK8: derive_terminal_state is an importable pure function.
"""

from __future__ import annotations

import inspect
import typing

import pytest

# AK8 / AK6: canonical importable surface from the story-contracts BC.
from agentkit.backend.story_context_manager import (
    ExitClass,
    TerminalState,
    derive_terminal_state,
    validate_exit_class_constraints,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import Story, StoryStatus
from agentkit.backend.story_context_manager.types import StoryType

# ---------------------------------------------------------------------------
# AK1 — derive_terminal_state: derivation + exhaustiveness
# ---------------------------------------------------------------------------


def test_terminal_state_has_exactly_open_done_cancelled() -> None:
    """TerminalState is exactly Open|Done|Cancelled (FK-59 §59.6.1)."""
    assert {member.value for member in TerminalState} == {
        "Open",
        "Done",
        "Cancelled",
    }


@pytest.mark.parametrize(
    "status,expected",
    [
        (StoryStatus.DONE, TerminalState.DONE),
        (StoryStatus.CANCELLED, TerminalState.CANCELLED),
        (StoryStatus.BACKLOG, TerminalState.OPEN),
        (StoryStatus.APPROVED, TerminalState.OPEN),
        (StoryStatus.IN_PROGRESS, TerminalState.OPEN),
    ],
)
def test_derive_terminal_state_maps_each_status(
    status: StoryStatus, expected: TerminalState
) -> None:
    """Done->Done, Cancelled->Cancelled, all others -> Open (FK-59 §59.6.1)."""
    assert derive_terminal_state(status) is expected


def test_derive_terminal_state_is_exhaustive_over_story_status() -> None:
    """Every real StoryStatus member maps to a value (no else hole, AK1).

    This is the exhaustiveness proof: each member of the SINGLE StoryStatus
    owner derives to a valid TerminalState. Because only Done/Cancelled are
    terminal and everything else falls to Open, any FUTURE non-terminal member
    is guaranteed to map to Open without changing the derivation.
    """
    for status in StoryStatus:
        result = derive_terminal_state(status)
        assert isinstance(result, TerminalState)
        if status is StoryStatus.DONE:
            assert result is TerminalState.DONE
        elif status is StoryStatus.CANCELLED:
            assert result is TerminalState.CANCELLED
        else:
            assert result is TerminalState.OPEN


def test_derive_terminal_state_only_done_and_cancelled_are_non_open() -> None:
    """Exactly the two terminal members leave Open (collector) semantics."""
    non_open = {
        status for status in StoryStatus
        if derive_terminal_state(status) is not TerminalState.OPEN
    }
    assert non_open == {StoryStatus.DONE, StoryStatus.CANCELLED}


# ---------------------------------------------------------------------------
# AK8 — pure, importable, no I/O, no StoryStatus duplication
# ---------------------------------------------------------------------------


def test_derive_terminal_state_is_pure_and_importable() -> None:
    """derive_terminal_state is a directly callable pure function (AK8).

    No I/O is performed and StoryStatus is consumed, not duplicated: the
    function signature takes the existing StoryStatus enum.
    """
    hints = typing.get_type_hints(derive_terminal_state)
    assert hints["status"] is StoryStatus
    assert hints["return"] is TerminalState
    # Pure: identical input yields identical output, repeatedly.
    assert derive_terminal_state(StoryStatus.IN_PROGRESS) is TerminalState.OPEN
    assert derive_terminal_state(StoryStatus.IN_PROGRESS) is TerminalState.OPEN


def test_terminal_state_does_not_duplicate_story_status() -> None:
    """TerminalState is the result view, NOT a second StoryStatus (FIX-THE-MODEL)."""
    # Open is a collector category that has no StoryStatus counterpart.
    assert "Open" not in {member.value for member in StoryStatus}
    # The non-terminal StoryStatus members (Backlog/Approved/In Progress) have
    # no individual TerminalState member of their own.
    assert {member.value for member in TerminalState} != {
        member.value for member in StoryStatus
    }


# ---------------------------------------------------------------------------
# AK2 — exit_class is not a free Story main field
# ---------------------------------------------------------------------------


def test_story_model_has_no_exit_class_field() -> None:
    """The Story stammdaten model carries no exit_class field (AK2, FK-59 §59.11)."""
    assert "exit_class" not in Story.model_fields
    assert "terminal_state" not in Story.model_fields


def test_story_context_model_has_no_exit_class_field() -> None:
    """StoryContext (runtime contract) carries no exit_class field (AK2)."""
    assert "exit_class" not in StoryContext.model_fields
    assert "terminal_state" not in StoryContext.model_fields


# ---------------------------------------------------------------------------
# AK7 — validate_exit_class_constraints directly (positive + #2/#3 negative)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal_state", list(TerminalState))
def test_constraint_allows_none_exit_class_for_any_terminal_state(
    terminal_state: TerminalState,
) -> None:
    """exit_class=None is always legal (AK4 positive)."""
    validate_exit_class_constraints(terminal_state, None)  # must not raise


@pytest.mark.parametrize("exit_class", list(ExitClass))
def test_constraint_allows_cancelled_with_any_exit_class(
    exit_class: ExitClass,
) -> None:
    """Cancelled + any exit_class is legal (AK4 positive)."""
    validate_exit_class_constraints(TerminalState.CANCELLED, exit_class)


@pytest.mark.parametrize("exit_class", list(ExitClass))
def test_constraint_rejects_done_with_exit_class(exit_class: ExitClass) -> None:
    """#2: Done + exit_class -> raise (AK3 negative)."""
    with pytest.raises(ValueError, match="exit_class"):
        validate_exit_class_constraints(TerminalState.DONE, exit_class)


@pytest.mark.parametrize("exit_class", list(ExitClass))
def test_constraint_rejects_open_with_exit_class(exit_class: ExitClass) -> None:
    """#3: Open (!= Cancelled) + exit_class -> raise (AK4 negative)."""
    with pytest.raises(ValueError, match="exit_class"):
        validate_exit_class_constraints(TerminalState.OPEN, exit_class)


def test_constraint_is_single_function_with_fixed_signature() -> None:
    """The constraint is one typed function with the fixed AG3-074 signature (AK7)."""
    sig = inspect.signature(validate_exit_class_constraints)
    params = list(sig.parameters)
    assert params == ["terminal_state", "exit_class"]
    assert sig.return_annotation in (None, "None")


# ---------------------------------------------------------------------------
# §59.12 — the six mandated tests (exact names, real invariants)
# ---------------------------------------------------------------------------


def test_implementation_contract_only_allowed_for_implementation() -> None:
    """§59.8 #1: implementation_contract is restricted to its allowed profile set.

    Asserts the existing restriction in
    ``story_context_manager/models.py`` (``_validate_contract_shape``): a
    non-allowed ``implementation_contract`` for a ``story_type`` whose profile
    does not permit it is fail-closed (ValueError). A research story has an
    empty ``allowed_implementation_contracts`` set, so any non-None contract is
    rejected; an implementation story accepts ``standard``.
    """
    from agentkit.backend.core_types import StoryMode
    from agentkit.backend.story_context_manager.types import ImplementationContract

    # Positive: implementation accepts the standard contract.
    ok = StoryContext(
        project_key="ak3",
        story_id="AK3-1",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        implementation_contract=ImplementationContract.STANDARD,
    )
    assert ok.implementation_contract is ImplementationContract.STANDARD

    # Negative: a research story may not carry an implementation_contract.
    with pytest.raises(ValueError, match="implementation_contract"):
        StoryContext(
            project_key="ak3",
            story_id="AK3-2",
            story_type=StoryType.RESEARCH,
            implementation_contract=ImplementationContract.STANDARD,
        )


def test_exit_class_only_allowed_when_terminal_state_cancelled() -> None:
    """§59.8 #2/#3: exit_class is only legal under terminal_state=Cancelled."""
    # Legal: Cancelled + every exit_class member.
    for exit_class in ExitClass:
        validate_exit_class_constraints(TerminalState.CANCELLED, exit_class)
    # Illegal: any non-Cancelled terminal_state + an exit_class.
    for terminal_state in (TerminalState.OPEN, TerminalState.DONE):
        for exit_class in ExitClass:
            with pytest.raises(ValueError):
                validate_exit_class_constraints(terminal_state, exit_class)


def test_operating_mode_is_runtime_derived_not_story_persisted() -> None:
    """§59.5/§59.8: operating_mode is a runtime-derived value, not a Story field.

    Asserts the existing resolution in
    ``control_plane/runtime.py`` (``_resolve_operating_mode``): the mode is
    derived from the run binding + lock, NOT stored on the Story/StoryContext
    models.
    """
    from datetime import UTC, datetime

    from agentkit.backend.control_plane.runtime import _resolve_operating_mode
    from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord

    now = datetime.now(UTC)
    lock = StoryExecutionLockRecord(
        project_key="ak3",
        story_id="AK3-1",
        run_id="run-1",
        lock_type="story_execution",
        status="ACTIVE",
        worktree_roots=(),
        binding_version="bind-1",
        activated_at=now,
        updated_at=now,
    )
    # No binding -> ai_augmented (derived, never persisted on the Story).
    assert _resolve_operating_mode(binding=None, lock=lock) == "ai_augmented"
    # operating_mode is not a persistent Story contract field.
    assert "operating_mode" not in Story.model_fields
    assert "operating_mode" not in StoryContext.model_fields


def test_binding_invalid_is_not_free_ai_augmented() -> None:
    """§59.8 #6: an invalid story binding resolves to binding_invalid, not a silent
    fallback to ai_augmented.

    Asserts the existing ``_resolve_operating_mode``: when a binding is present
    but the lock is not ACTIVE, the resolved mode is the distinct
    ``binding_invalid`` value (fail-closed), never a quiet ``ai_augmented``.
    """
    from datetime import UTC, datetime

    from agentkit.backend.control_plane.records import SessionRunBindingRecord
    from agentkit.backend.control_plane.runtime import _resolve_operating_mode
    from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord

    now = datetime.now(UTC)
    binding = SessionRunBindingRecord(
        session_id="sess-1",
        project_key="ak3",
        story_id="AK3-1",
        run_id="run-1",
        principal_type="story_worker",
        worktree_roots=(),
        binding_version="bind-1",
        updated_at=now,
    )
    inactive_lock = StoryExecutionLockRecord(
        project_key="ak3",
        story_id="AK3-1",
        run_id="run-1",
        lock_type="story_execution",
        status="INVALID",
        worktree_roots=(),
        binding_version="bind-1",
        activated_at=now,
        updated_at=now,
    )
    resolved = _resolve_operating_mode(binding=binding, lock=inactive_lock)
    assert resolved == "binding_invalid"
    assert resolved != "ai_augmented"


def test_integration_stabilization_is_not_third_operating_mode() -> None:
    """§59.8 #7: integration_stabilization is an implementation_contract, NOT an
    operating_mode.

    Asserts the existing typed surfaces: ``integration_stabilization`` lives in
    the ``ImplementationContract`` enum and is NOT one of the resolved
    OperatingMode literals (control_plane). The operating-mode space stays
    exactly {ai_augmented, story_execution, binding_invalid}.
    """
    import typing

    from agentkit.backend.control_plane import runtime as cp_runtime
    from agentkit.backend.story_context_manager.types import ImplementationContract

    assert ImplementationContract.INTEGRATION_STABILIZATION.value == (
        "integration_stabilization"
    )
    operating_modes = set(typing.get_args(cp_runtime.OperatingMode))
    assert operating_modes == {"ai_augmented", "story_execution", "binding_invalid"}
    assert "integration_stabilization" not in operating_modes


def test_phase_state_mode_is_execution_route_alias() -> None:
    """§59.5: the non-fast PhaseState.mode family aliases the execution_route values.

    Asserts the existing typed surfaces (FK-24 §24.3.2): ``PhaseStateMode``'s
    standard (non-fast) members EXECUTION/EXPLORATION carry exactly the
    ``StoryMode`` execution_route values; ``fast`` is NOT a ``StoryMode``
    execution_route value but a separate mode-axis member.
    """
    from agentkit.backend.core_types import StoryMode
    from agentkit.backend.pipeline_engine.phase_executor import PhaseStateMode

    # The standard family aliases the execution_route (StoryMode) values.
    assert PhaseStateMode.EXECUTION.value == StoryMode.EXECUTION.value
    assert PhaseStateMode.EXPLORATION.value == StoryMode.EXPLORATION.value
    # fast is NOT an execution_route value.
    story_mode_values = {member.value for member in StoryMode}
    assert PhaseStateMode.FAST.value not in story_mode_values
    assert PhaseStateMode.FAST.value == "fast"
