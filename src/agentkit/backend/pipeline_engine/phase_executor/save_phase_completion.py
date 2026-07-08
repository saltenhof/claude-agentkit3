"""Write-ordering helper for phase-completing persistence.

Canonical implementation of FK-39 §39.4.4: AttemptRecord BEFORE PhaseState.

Crash-safety invariant: on a crash between the two writes the AttemptRecord
stays readable and the PhaseState shows the previous state. Recovery logic
can build on that.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.backend.state_backend.pipeline_runtime_store import (
    save_attempt,
    save_phase_state,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.pipeline_engine.phase_executor.models import PhaseState
    from agentkit.backend.pipeline_engine.phase_executor.records import AttemptRecord

__all__ = ("EnvelopeWithState", "save_phase_completion")


@runtime_checkable
class EnvelopeWithState(Protocol):
    """Minimal protocol: any object that exposes a ``state`` attribute.

    Both ``PhaseEnvelope`` and the engine-internal ``_WrapState`` adapter
    satisfy this protocol, so ``save_phase_completion`` does not need to
    import either concrete type.
    """

    @property
    def state(self) -> PhaseState:
        ...


def save_phase_completion(
    story_dir: Path,
    *,
    envelope: EnvelopeWithState,
    attempt_record: AttemptRecord,
) -> None:
    """Persist AttemptRecord BEFORE PhaseState (FK-39 §39.4.4 write-ordering).

    This is the single canonical call site that enforces the phase-completing
    write ordering: ``save_attempt`` first, then ``save_phase_state``.

    Crash-safety invariant: on a crash between the two writes the AttemptRecord
    stays in the DB and the PhaseState still shows the previous state. Recovery
    logic reads the AttemptRecord and builds on the last known PhaseState
    (FK-39 §39.4.4 lines 431-437).

    Args:
        story_dir: Root directory for this story's persistent state.
        envelope: Any object exposing a ``.state: PhaseState`` property;
            accepts both ``PhaseEnvelope`` and the engine-internal
            ``_WrapState`` adapter.
        attempt_record: The ``AttemptRecord`` documenting this attempt; always
            written first.
    """
    save_attempt(story_dir, attempt_record)       # AttemptRecord FIRST
    save_phase_state(story_dir, envelope.state)   # PhaseState AFTERWARDS
