"""PhaseEnvelopeStore -- BC-owned store sub for phase-state persistence.

This is the single facade through which the pipeline engine reads and
writes PhaseState. It enforces the FK-39 persistence boundary:

- ``save``: only ``envelope.state`` is persisted; ``envelope.runtime``
  is deliberately discarded (it is process-local, not durable).
- ``load``: constructs a fresh ``RuntimeMetadata`` with ``origin=LOADED``
  and the current process identity. The stored state is never mutated.

Source of truth: FK-39 §39.1 / §39.3; bc-cut-decisions.md §BC 1 Layer 1
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
from agentkit.pipeline_engine.phase_envelope.runtime import PhaseOrigin, RuntimeMetadata

if TYPE_CHECKING:
    from agentkit.pipeline_engine.phase_envelope.repository import (
        PhaseEnvelopeRepository,
    )
    from agentkit.pipeline_engine.phase_executor.models import PhaseName, PhaseState


def _build_runtime(*, origin: PhaseOrigin) -> RuntimeMetadata:
    """Construct a fresh RuntimeMetadata for the current process."""
    return RuntimeMetadata(origin=origin)


class PhaseEnvelopeStore:
    """BC-owned facade for reading and writing PhaseEnvelopes.

    The store is the single point of contact between the pipeline engine
    and the persistence layer for phase states. It guarantees:

    1. On ``save``: only ``envelope.state`` (durable) is written;
       ``envelope.runtime`` (ephemeral) is silently discarded.
    2. On ``load``: a fresh ``RuntimeMetadata`` with ``origin=LOADED`` is
       constructed locally, not read from storage.
    3. On fresh start (no stored state): ``load`` returns ``None``.

    Args:
        repository: The storage backend implementing
            ``PhaseEnvelopeRepository``.
    """

    def __init__(self, repository: PhaseEnvelopeRepository) -> None:
        self._repository = repository

    def load(self, story_id: str, phase: PhaseName) -> PhaseEnvelope | None:
        """Load a PhaseEnvelope from storage.

        If no state is found for (story_id, phase), returns ``None``.
        When state is found, the runtime is reconstructed with
        ``origin=PhaseOrigin.LOADED``.

        Args:
            story_id: Story identifier.
            phase: Pipeline phase name.

        Returns:
            A ``PhaseEnvelope`` with a freshly constructed runtime, or
            ``None`` if no state has been persisted yet.
        """
        state = self._repository.load_state(story_id, phase)
        if state is None:
            return None
        return PhaseEnvelope(
            state=state,
            runtime=_build_runtime(origin=PhaseOrigin.LOADED),
        )

    def save(self, envelope: PhaseEnvelope) -> None:
        """Persist the durable state from an envelope.

        Only ``envelope.state`` is written; ``envelope.runtime`` is
        discarded. This enforces the FK-39 persistence boundary.

        Args:
            envelope: The envelope whose state should be persisted.
        """
        self._repository.save_state(envelope.state)

    def save_state(self, state: PhaseState) -> None:
        """Persist a PhaseState directly (convenience overload).

        Used by engine internals that work with bare PhaseState objects.

        Args:
            state: The phase state to persist.
        """
        self._repository.save_state(state)

    def exists(self, story_id: str, phase: PhaseName) -> bool:
        """Check whether a state has been persisted for (story_id, phase).

        Args:
            story_id: Story identifier.
            phase: Pipeline phase name.

        Returns:
            ``True`` if state exists, ``False`` otherwise.
        """
        return self._repository.exists_state(story_id, phase)

    @staticmethod
    def make_fresh_envelope(state: PhaseState) -> PhaseEnvelope:
        """Wrap a newly created PhaseState in an envelope with origin=NEW.

        Used by the runner when starting a fresh phase (no prior
        persistent state). The runtime is constructed with
        ``origin=PhaseOrigin.NEW``.

        Args:
            state: The freshly created PhaseState.

        Returns:
            A ``PhaseEnvelope`` with ``origin=NEW``.
        """
        return PhaseEnvelope(
            state=state,
            runtime=_build_runtime(origin=PhaseOrigin.NEW),
        )
