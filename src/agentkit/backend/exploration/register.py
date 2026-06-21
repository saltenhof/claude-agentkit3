"""Init-hook: register the exploration BC's ENTWURF artifact producer.

Called ONCE by the composition-root (``build_producer_registry``) before any
pipeline run, mirroring ``verify_system.register.register_verify_producers``.
Without this registration the ``EnvelopeValidator`` rejects any ENTWURF
envelope fail-closed (``ProducerNotRegisteredError``) — so wiring this hook is
what makes the change-frame ENTWURF write/read path work in production, not just
in a locally-seeded test registry. Option Y (PO 2026-06-05): the ENTWURF
envelope is WRITTEN by the spawned exploration worker (AG3-055, BC
``agent-skills``); AG3-045 (this BC) registers the producer (plumbing) and
consumes / validates the persisted change-frame.

Source:
- ``concept/_meta/bc-cut-decisions.md §BC 5`` — the exploration worker owns
  writing the change-frame (ArtifactClass.ENTWURF); AG3-045 owns the schema +
  consume/validate plumbing.
- ``stories/AG3-023-artifact-manager-migration/story.md §2.1.6.1`` — dedicated
  ``register.py`` init-hook per BC.
- ``FK-71 §71.1.1`` — ENTWURF artifact class (worker draft artifact).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentkit.backend.artifacts import ProducerType
from agentkit.backend.core_types import ArtifactClass

if TYPE_CHECKING:
    from agentkit.backend.artifacts import ProducerRegistry

#: Canonical producer name stamped on the exploration ENTWURF envelope.
EXPLORATION_ENTWURF_PRODUCER: Final[str] = "exploration-worker"

#: Stage id of the exploration change-frame artifact (envelope ``stage`` field;
#: matches ``^[a-z][a-z0-9_-]{0,63}$``). Written by the exploration worker
#: (AG3-055), consumed/validated by the exploration phase handler (AG3-045).
EXPLORATION_ENTWURF_STAGE: Final[str] = "exploration-drafting"

#: (ArtifactClass, producer-name, ProducerType) — SSOT for the exploration
#: producers. The exploration worker is a WORKER-type producer (FK-71 §71.1.1).
_EXPLORATION_PRODUCERS: Final[
    tuple[tuple[ArtifactClass, str, ProducerType], ...]
] = ((ArtifactClass.ENTWURF, EXPLORATION_ENTWURF_PRODUCER, ProducerType.WORKER),)


def register_exploration_producers(registry: ProducerRegistry) -> None:
    """Register the exploration BC's ENTWURF producer.

    Idempotent: re-running with the same registry overwrites the entries with
    identical values (AG3-022 §2.1.5.1 init strategy). The call belongs in the
    composition-root.

    Args:
        registry: A fresh or already-populated ``ProducerRegistry``. The
            function mutates the registry state.
    """
    for artifact_class, name, producer_type in _EXPLORATION_PRODUCERS:
        registry.register(artifact_class, name, producer_type)


__all__ = [
    "EXPLORATION_ENTWURF_PRODUCER",
    "EXPLORATION_ENTWURF_STAGE",
    "register_exploration_producers",
]
