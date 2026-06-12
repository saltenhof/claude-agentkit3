"""Integrity-gate ai_augmented mode-exclusion (AG3-097 AK1, FK-56 §56.7a/§56.10).

The ``ai_augmented`` (free / unbound) operating mode has NO integrity gate: an
accidental ``IntegrityGate.evaluate`` invocation in that mode raises a typed
:class:`IntegrityGateNotApplicableError` BEFORE any integrity work -- no
``integrity_gate_started`` / ``integrity_gate_result`` event, no closure
FAIL-code. ``story_execution`` (the default) and ``binding_invalid`` proceed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.governance.integrity_gate import (
    IntegrityGate,
    IntegrityGateNotApplicableError,
)
from agentkit.governance.integrity_gate.mode_guard import guard_integrity_gate_mode
from agentkit.story_context_manager.types import StoryType

if TYPE_CHECKING:
    from pathlib import Path


class _RecordingStatePort:
    """First-class state port that RECORDS whether any integrity work started.

    NOT a mock: it is a faithful, fail-closed stand-in for the read-only state
    port. The point is to prove the mode guard aborts BEFORE the gate touches the
    state port at all -- so ``resolve_runtime_scope`` (the first integrity step)
    must never be called in the ai_augmented mode.
    """

    def __init__(self) -> None:
        self.resolve_calls = 0

    def resolve_runtime_scope(self, story_dir: Path) -> None:
        del story_dir
        self.resolve_calls += 1
        return None


def test_guard_rejects_ai_augmented() -> None:
    """The bare guard raises for ai_augmented (FK-56 §56.7a/§56.10)."""
    with pytest.raises(IntegrityGateNotApplicableError):
        guard_integrity_gate_mode("ai_augmented")


def test_guard_allows_story_execution_and_binding_invalid() -> None:
    """The guard is a no-op for the bound / binding_invalid modes."""
    guard_integrity_gate_mode("story_execution")
    guard_integrity_gate_mode("binding_invalid")


def test_evaluate_aborts_before_any_work_in_ai_augmented(tmp_path: Path) -> None:
    """ai_augmented -> typed error BEFORE the gate touches the state port (AK1).

    The recording state port proves no integrity work began (no scope resolution,
    hence no dimension evaluation, hence no event and no FAIL-code could have been
    produced).
    """
    state_port = _RecordingStatePort()
    gate = IntegrityGate(state_port)  # type: ignore[arg-type]

    with pytest.raises(IntegrityGateNotApplicableError):
        gate.evaluate(
            tmp_path,
            StoryType.IMPLEMENTATION,
            operating_mode="ai_augmented",
        )

    assert state_port.resolve_calls == 0


def test_evaluate_default_mode_is_story_execution_and_runs(tmp_path: Path) -> None:
    """The default operating_mode is story_execution: the gate runs (no abort).

    The recording state port proves the gate proceeded PAST the mode guard into
    real integrity work (``resolve_runtime_scope`` was called). The default bound
    mode does not raise :class:`IntegrityGateNotApplicableError`.
    """
    state_port = _RecordingStatePort()
    gate = IntegrityGate(state_port)  # type: ignore[arg-type]

    # The default mode is story_execution -> the gate enters integrity work
    # (it calls resolve_runtime_scope). It never raises the mode-exclusion error.
    try:
        gate.evaluate(tmp_path, StoryType.IMPLEMENTATION)
    except IntegrityGateNotApplicableError:  # pragma: no cover - must NOT happen
        pytest.fail("default story_execution mode must not be mode-excluded")
    except Exception:  # noqa: BLE001 - downstream dimension wiring is not under test
        pass

    assert state_port.resolve_calls == 1
