"""Write-ordering helper for phasenabschliessende Persistenz.

Canonical implementation of FK-39 §39.4.4: AttemptRecord BEFORE PhaseState.

Crash-Safety-Invariante: bei Crash zwischen den beiden Schreibvorgaengen
bleibt der AttemptRecord lesbar und der PhaseState zeigt den vorherigen
Stand. Recovery-Logik kann darauf aufsetzen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.state_backend.store import save_attempt, save_phase_state

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.pipeline_engine.phase_executor.records import AttemptRecord
    from agentkit.story_context_manager.models import PhaseState

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

    This is the single canonical call site that enforces the phasenabschliessende
    write ordering: ``save_attempt`` first, then ``save_phase_state``.

    Crash-Safety-Invariante: bei Crash zwischen den beiden Schreibvorgaengen
    bleibt der AttemptRecord in der DB und der PhaseState zeigt noch den
    vorherigen Stand. Recovery-Logik liest den AttemptRecord und setzt auf
    dem letzten bekannten PhaseState auf (FK-39 §39.4.4 Z. 431-437).

    Args:
        story_dir: Root directory for this story's persistent state.
        envelope: Any object exposing a ``.state: PhaseState`` property;
            accepts both ``PhaseEnvelope`` and the engine-internal
            ``_WrapState`` adapter.
        attempt_record: The ``AttemptRecord`` documenting this attempt; always
            written first.
    """
    save_attempt(story_dir, attempt_record)       # AttemptRecord ZUERST
    save_phase_state(story_dir, envelope.state)   # PhaseState DANACH
