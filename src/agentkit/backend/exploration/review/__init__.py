"""Exploration exit-gate review (AG3-046, FK-23 §23.5).

The three-stage exit-gate that ends the exploration phase:

* Stage 1 -- :class:`DocFidelityChecker` (document fidelity, §23.5.1)
* Stage 2a -- :class:`DesignReviewRunner` (design review + remediation, §23.5.2)
* Stage 2b -- :class:`DesignChallengeRunner` (design challenge, §23.5.3; class
  provided, activation deferred to AG3-047)

orchestrated by :class:`ExplorationReview` into an :class:`ExplorationGateResult`
(``APPROVED`` | ``REJECTED`` | ``PENDING``). The exploration phase handler
(:class:`~agentkit.backend.exploration.phase.ExplorationPhaseHandler`) drives this gate
and maps the result onto ``ExplorationPayload.gate_status``.
"""

from __future__ import annotations

from agentkit.backend.exploration.review.design_challenge import (
    DesignChallengeResult,
    DesignChallengeRunner,
)
from agentkit.backend.exploration.review.design_review import (
    ChangeFrameReviser,
    DesignReviewResult,
    DesignReviewRunner,
)
from agentkit.backend.exploration.review.doc_fidelity import (
    DocFidelityChecker,
    DocFidelityResult,
)
from agentkit.backend.exploration.review.persistence import (
    ArtifactReviewResultSink,
    ReviewResultSink,
)
from agentkit.backend.exploration.review.register import (
    EXPLORATION_REVIEW_PRODUCER,
    register_exploration_review_producers,
)
from agentkit.backend.exploration.review.review import (
    ExplorationGateResult,
    ExplorationReview,
)

__all__ = [
    "EXPLORATION_REVIEW_PRODUCER",
    "ArtifactReviewResultSink",
    "ChangeFrameReviser",
    "DesignChallengeResult",
    "DesignChallengeRunner",
    "DesignReviewResult",
    "DesignReviewRunner",
    "DocFidelityChecker",
    "DocFidelityResult",
    "ExplorationGateResult",
    "ExplorationReview",
    "ReviewResultSink",
    "register_exploration_review_producers",
]
