"""PhaseEnvelopeRepository -- storage protocol for PhaseState persistence.

This Protocol defines the contract that concrete repository implementations
must satisfy. The PhaseEnvelopeStore uses this protocol to remain decoupled
from the underlying persistence driver (SQLite, Postgres, etc.).

Concrete implementations live in ``agentkit.state_backend.store``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.pipeline_engine.phase_executor.models import PhaseName, PhaseState


@runtime_checkable
class PhaseEnvelopeRepository(Protocol):
    """Protocol for phase-state storage backends.

    Implementors connect to the concrete persistence layer (SQLite or
    Postgres) and expose the three operations the store needs:

    - ``load_state``: return the latest persisted ``PhaseState`` for the
      given story and phase, or ``None`` if nothing has been saved yet.
    - ``save_state``: persist a ``PhaseState``; must be idempotent on
      repeated calls.
    - ``exists_state``: lightweight existence check (no deserialization).
    """

    def load_state(
        self,
        story_id: str,
        phase: PhaseName,
    ) -> PhaseState | None:
        """Load the persisted PhaseState for (story_id, phase).

        Args:
            story_id: The story identifier.
            phase: The pipeline phase name.

        Returns:
            The persisted ``PhaseState``, or ``None`` if not found.
        """
        ...

    def save_state(self, state: PhaseState) -> None:
        """Persist a PhaseState.

        Args:
            state: The phase state to persist.
        """
        ...

    def exists_state(self, story_id: str, phase: PhaseName) -> bool:
        """Check whether a PhaseState exists for (story_id, phase).

        Args:
            story_id: The story identifier.
            phase: The pipeline phase name.

        Returns:
            ``True`` if a state record exists, ``False`` otherwise.
        """
        ...
