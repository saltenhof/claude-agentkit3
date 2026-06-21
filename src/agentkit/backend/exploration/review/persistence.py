"""Persistence of exploration-review evaluator results (FK-23 §23.5 / FK-71).

Each gate stage (doc-fidelity, design-review, design-challenge) produces a
:class:`~agentkit.backend.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluatorResult`
that must be persisted as a QA artifact so the stage result carries a real,
auditable :class:`~agentkit.backend.artifacts.reference.ArtifactReference` -- never a
fabricated reference (ZERO DEBT / NO ERROR BYPASSING).

:class:`ReviewResultSink` is the injected boundary port; the concrete
:class:`ArtifactReviewResultSink` writes the result through the single
authorized write surface (:class:`~agentkit.backend.artifacts.manager.ArtifactManager`,
FK-71 §71.2). The exploration review core depends on the port, the
composition-root wires the concrete sink (mirroring the change-frame adapter).
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
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.exploration.review.register import EXPLORATION_REVIEW_PRODUCER
from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import LlmVerdict

if TYPE_CHECKING:
    from agentkit.backend.artifacts import ArtifactManager
    from agentkit.backend.artifacts.reference import ArtifactReference
    from agentkit.backend.exploration.change_frame import ChangeFrame
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluatorResult,
    )

#: Wire-string ``EnvelopeStatus`` of a clean evaluator PASS vs. any other
#: verdict. A non-PASS verdict persists a ``FAIL`` envelope so the audit trail
#: shows the gate-blocking outcome (no silent PASS at the artifact boundary).
_VERDICT_ENVELOPE_STATUS = {
    LlmVerdict.PASS: EnvelopeStatus.PASS,
    LlmVerdict.PASS_WITH_CONCERNS: EnvelopeStatus.WARN,
    LlmVerdict.FAIL: EnvelopeStatus.FAIL,
}


@runtime_checkable
class ReviewResultSink(Protocol):
    """Persist a stage evaluator result and return its typed reference."""

    def persist(
        self,
        *,
        change_frame: ChangeFrame,
        stage: str,
        review_round: int,
        evaluator_result: StructuredEvaluatorResult,
    ) -> ArtifactReference:
        """Store the evaluator result as a QA artifact (fail-closed).

        Args:
            change_frame: The change-frame under review (identity source).
            stage: The gate-stage wire id (e.g. ``"doc_fidelity"``).
            review_round: 1-based review round.
            evaluator_result: The validated evaluator result to persist.

        Returns:
            The typed :class:`ArtifactReference` of the persisted artifact.
        """
        ...


class ArtifactReviewResultSink:
    """Concrete :class:`ReviewResultSink` over the :class:`ArtifactManager`.

    Writes each stage evaluator result as a ``QA`` artifact through the single
    authorized write surface (FK-71 §71.2). The producer is registered by
    ``register_exploration_review_producers`` (init-hook), so a missing
    registration fails closed at the validator (``ProducerNotRegisteredError``).
    """

    def __init__(self, artifact_manager: ArtifactManager) -> None:
        """Initialize the sink.

        Args:
            artifact_manager: The single authorized artifact write surface (DI).
        """
        self._manager = artifact_manager

    def persist(
        self,
        *,
        change_frame: ChangeFrame,
        stage: str,
        review_round: int,
        evaluator_result: StructuredEvaluatorResult,
    ) -> ArtifactReference:
        """Persist the evaluator result and return its reference.

        Args:
            change_frame: The change-frame under review (identity source for the
                envelope ``story_id`` / ``run_id``).
            stage: The gate-stage wire id (envelope ``stage`` segment).
            review_round: 1-based review round (envelope ``attempt``).
            evaluator_result: The validated evaluator result to persist.

        Returns:
            The typed :class:`ArtifactReference` returned by the manager.

        Raises:
            ProducerNotRegisteredError: If the exploration-review QA producer is
                not registered (fail-closed).
            EnvelopeFieldError: If a mandatory envelope field is invalid.
        """
        now = datetime.now(tz=UTC)
        envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id=change_frame.story_id,
            run_id=change_frame.run_id,
            stage=_stage_id(stage, review_round),
            attempt=review_round,
            producer=Producer(
                type=ProducerType.LLM_REVIEWER,
                name=EXPLORATION_REVIEW_PRODUCER,
                id=ProducerId(
                    f"{EXPLORATION_REVIEW_PRODUCER}-{change_frame.run_id}-"
                    f"{stage}-r{review_round}"
                ),
            ),
            started_at=now,
            finished_at=now,
            status=_VERDICT_ENVELOPE_STATUS[evaluator_result.verdict],
            artifact_class=ArtifactClass.QA,
            payload=evaluator_result.model_dump(mode="json"),
        )
        return self._manager.write(envelope)


def _stage_id(stage: str, review_round: int) -> str:
    """Build the envelope ``stage`` id for a review stage + round.

    Args:
        stage: The gate-stage wire id (e.g. ``"design_review"``).
        review_round: 1-based review round.

    Returns:
        A stage id matching ``^[a-z][a-z0-9_-]{0,63}$`` (envelope contract),
        e.g. ``"exploration-review-design_review-r2"``.
    """
    return f"exploration-review-{stage}-r{review_round}"


__all__ = ["ArtifactReviewResultSink", "ReviewResultSink"]
