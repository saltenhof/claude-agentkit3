"""Init-hook: register the exploration-review's QA artifact producer (FK-71).

The three exit-gate stages (FK-23 §23.5) persist their evaluator results as
``QA`` artifacts (FK-71 §71.1.1). Without a registered producer the
``EnvelopeValidator`` rejects those envelopes fail-closed
(``ProducerNotRegisteredError``); registering this producer is what makes the
review-result write path work in production -- not just in a locally-seeded test
registry. The producer is an ``LLM_REVIEWER`` (the stages are Layer-2 LLM
evaluations, FK-11 §11.5.1). Wired into ``build_producer_registry`` at the
composition-root, mirroring ``register_exploration_producers`` (AG3-045).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentkit.backend.artifacts import ProducerType
from agentkit.backend.core_types import ArtifactClass

if TYPE_CHECKING:
    from agentkit.backend.artifacts import ProducerRegistry

#: Canonical producer name stamped on the exploration-review QA envelopes
#: (FK-23 §23.5, the three-stage exit-gate).
EXPLORATION_REVIEW_PRODUCER: Final[str] = "exploration-review"


def register_exploration_review_producers(registry: ProducerRegistry) -> None:
    """Register the exploration-review QA producer (idempotent).

    Args:
        registry: A fresh or already-populated ``ProducerRegistry``. The
            function mutates the registry state (idempotent re-registration).
    """
    registry.register(
        ArtifactClass.QA, EXPLORATION_REVIEW_PRODUCER, ProducerType.LLM_REVIEWER
    )


__all__ = [
    "EXPLORATION_REVIEW_PRODUCER",
    "register_exploration_review_producers",
]
