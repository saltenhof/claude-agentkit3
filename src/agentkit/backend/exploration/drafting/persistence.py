"""Persistence of the worker-produced change-frame (FK-23 §23.4.3 / FK-71).

The exploration worker (AG3-055) produces the FK-23 change-frame; it must be
persisted as the typed ``ArtifactClass.ENTWURF`` envelope through the single
authorized write surface (:class:`~agentkit.backend.artifacts.manager.ArtifactManager`,
FK-71 §71.2) so the AG3-045 :class:`~agentkit.backend.exploration.phase.ExplorationPhaseHandler`
can later read / validate it. :class:`ChangeFrameSink` is the injected boundary
port; the concrete :class:`ArtifactChangeFrameSink` writes the ENTWURF envelope
using the producer registered by ``register_exploration_producers`` (a missing
registration fails closed at the validator). This mirrors the AG3-046
``ReviewResultSink`` / ``ArtifactReviewResultSink`` split: the bloodgroup-A
drafting core depends on the port, the composition-root wires the concrete sink.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.backend.artifacts import (
    ArtifactEnvelope,
    EnvelopeStatus,
    Producer,
    ProducerId,
    ProducerType,
)
from agentkit.backend.artifacts.envelope import ENVELOPE_SCHEMA_VERSION
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.exploration.register import (
    EXPLORATION_ENTWURF_PRODUCER,
    EXPLORATION_ENTWURF_STAGE,
)

if TYPE_CHECKING:
    from agentkit.backend.artifacts import ArtifactManager
    from agentkit.backend.artifacts.reference import ArtifactReference
    from agentkit.backend.exploration.change_frame import ChangeFrame


@runtime_checkable
class ChangeFrameSink(Protocol):
    """Persist the worker change-frame as its ENTWURF envelope (fail-closed)."""

    def persist(
        self, change_frame: ChangeFrame, *, attempt: int = 1
    ) -> ArtifactReference:
        """Store the change-frame as an ``ArtifactClass.ENTWURF`` envelope.

        Args:
            change_frame: The validated worker-produced change-frame (identity
                source for the envelope ``story_id`` / ``run_id``).
            attempt: 1-based draft attempt (envelope ``attempt``).

        Returns:
            The typed :class:`ArtifactReference` of the persisted ENTWURF
            envelope.
        """
        ...


class ArtifactChangeFrameSink:
    """Concrete :class:`ChangeFrameSink` over the :class:`ArtifactManager`.

    Writes the change-frame as an ``ArtifactClass.ENTWURF`` envelope through the
    single authorized write surface (FK-71 §71.2). The producer is registered by
    ``register_exploration_producers`` (init-hook); a missing registration fails
    closed at the validator (``ProducerNotRegisteredError``).
    """

    def __init__(self, artifact_manager: ArtifactManager) -> None:
        """Initialize the sink.

        Args:
            artifact_manager: The single authorized artifact write surface (DI).
        """
        self._manager = artifact_manager

    def persist(
        self, change_frame: ChangeFrame, *, attempt: int = 1
    ) -> ArtifactReference:
        """Persist the change-frame ENTWURF envelope and return its reference.

        Args:
            change_frame: The validated worker change-frame.
            attempt: 1-based draft attempt counter (envelope ``attempt``).

        Returns:
            The typed :class:`ArtifactReference` returned by the manager.

        Raises:
            ProducerNotRegisteredError: When the exploration ENTWURF producer is
                not registered (fail-closed).
            EnvelopeFieldError: When a mandatory envelope field is invalid.
        """
        now = datetime.now(tz=UTC)
        envelope = ArtifactEnvelope(
            schema_version=ENVELOPE_SCHEMA_VERSION,
            story_id=change_frame.story_id,
            run_id=change_frame.run_id,
            stage=EXPLORATION_ENTWURF_STAGE,
            attempt=attempt,
            producer=Producer(
                type=ProducerType.WORKER,
                name=EXPLORATION_ENTWURF_PRODUCER,
                id=ProducerId(
                    f"{EXPLORATION_ENTWURF_PRODUCER}-{change_frame.run_id}"
                ),
            ),
            started_at=now,
            finished_at=now,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.ENTWURF,
            payload=change_frame.model_dump(mode="json"),
        )
        return self._manager.write(envelope)


__all__ = ["ArtifactChangeFrameSink", "ChangeFrameSink"]
