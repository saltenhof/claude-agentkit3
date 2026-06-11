"""Init-hook: register the implementation BC's HANDOVER artifact producer.

Called ONCE by the composition-root (``build_producer_registry``) before any
pipeline run, mirroring ``exploration.register`` / ``verify_system.register``.
Without this registration the ``EnvelopeValidator`` rejects any HANDOVER
envelope fail-closed (``ProducerNotRegisteredError``) — so wiring this hook is
what makes the worker handover write path work in production, not just in a
locally-seeded test registry.

Source:
- ``FK-26 §26.7`` — handover package (worker -> QA-subflow handover).
- ``FK-71 §71.1.1`` — HANDOVER artifact class (worker handover artifact).
- ``stories/AG3-023-artifact-manager-migration/story.md §2.1.6.1`` — dedicated
  ``register.py`` init-hook per BC.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentkit.artifacts import ProducerType
from agentkit.core_types import ArtifactClass

if TYPE_CHECKING:
    from agentkit.artifacts import ProducerRegistry

#: Canonical producer name stamped on the worker HANDOVER envelope (FK-26 §26.7).
IMPLEMENTATION_HANDOVER_PRODUCER: Final[str] = "worker-handover"

#: Stage id of the handover artifact (envelope ``stage`` field; matches
#: ``^[a-z][a-z0-9_-]{0,63}$``). Written by the HandoverPackager (AG3-044).
IMPLEMENTATION_HANDOVER_STAGE: Final[str] = "implementation-handover"

#: (ArtifactClass, producer-name, ProducerType) — SSOT for the implementation
#: producers. The handover is a WORKER-type producer (FK-71 §71.1.1).
_IMPLEMENTATION_PRODUCERS: Final[
    tuple[tuple[ArtifactClass, str, ProducerType], ...]
] = (
    (ArtifactClass.HANDOVER, IMPLEMENTATION_HANDOVER_PRODUCER, ProducerType.WORKER),
)


def register_implementation_producers(registry: ProducerRegistry) -> None:
    """Register the implementation BC's HANDOVER producer.

    Idempotent: re-running with the same registry overwrites the entries with
    identical values (AG3-022 §2.1.5.1 init strategy). The call belongs in the
    composition-root.

    Args:
        registry: A fresh or already-populated ``ProducerRegistry``. The
            function mutates the registry state.
    """
    for artifact_class, name, producer_type in _IMPLEMENTATION_PRODUCERS:
        registry.register(artifact_class, name, producer_type)


__all__ = [
    "IMPLEMENTATION_HANDOVER_PRODUCER",
    "IMPLEMENTATION_HANDOVER_STAGE",
    "register_implementation_producers",
]
