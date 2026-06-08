"""PhaseEnvelope -- combines durable PhaseState with ephemeral RuntimeMetadata.

The envelope is the unit that the PipelineEngine and PhaseHandlers operate on.
Only ``envelope.state`` is persisted; ``envelope.runtime`` is always
reconstructed locally and is never written to storage.

Source of truth: FK-39 §39.1 / §39.3
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.pipeline_engine.phase_envelope.runtime import RuntimeMetadata
    from agentkit.pipeline_engine.phase_executor.models import PhaseState


@dataclass(frozen=True, slots=True)
class PhaseEnvelope:
    """Combines durable PhaseState with ephemeral RuntimeMetadata.

    The two halves have different lifetimes:

    - ``state``: persisted via ``PhaseEnvelopeStore.save``; survives crashes.
    - ``runtime``: process-local only; reconstructed on every load with fresh
      values (``origin=LOADED``).

    The model is frozen so that handlers cannot accidentally mutate it in
    place -- they must return an updated ``PhaseState`` via ``HandlerResult``.

    Attributes:
        state: Durable phase state (persisted).
        runtime: Ephemeral runtime metadata (never persisted).
    """

    state: PhaseState
    runtime: RuntimeMetadata
