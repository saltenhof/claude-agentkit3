"""Layer-2 review-completion telemetry sink (FK-27 §27.4.3 / §27.5.5).

The ``guard.multi_llm`` recurring guard (Gate 2, REF-036, FK-27 §27.4.3) counts
canonical ``llm_call_complete`` execution events -- one per mandatory reviewer
role (``qa_review`` / ``semantic_review`` / ``doc_fidelity``). FK-27 §27.4.3 is
explicit: ``llm_call_complete`` may be emitted ONLY after the review artefact
(§27.5.5) has been written successfully -- never on a bare API response. This
sink is the emission seam: the QA-subflow (``system.run_qa_subflow`` via
``_run_data_layer_kind``) calls :meth:`ReviewCompletionSink.review_completed`
AFTER each Layer-2 review envelope write succeeds, carrying the reviewer role so
the guard's per-role count is meaningful.

The verify-system BC owns the Protocol; the productive telemetry adapter (which
emits ``EventType.LLM_CALL_COMPLETE`` through the canonical
``StateBackendEmitter``) is wired at the composition root, keeping this BC free
of a telemetry import (BC-topology, AG3-035). The default No-op sink keeps the
test path inert WITHOUT weakening the guard: the guard counts canonical events,
not sink calls -- a missing emission simply leaves the count at 0, which the
BLOCKING guard reads as FAIL (fail-closed, NO ERROR BYPASSING).

Sources:
  - FK-27 §27.4.3 -- ``guard.multi_llm`` counts ``llm_call_complete`` per role,
    emitted only after the review artefact (§27.5.5) is written.
  - FK-37 §37.1.6 -- missing LLM reviews are a HARD BLOCKER.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "NullReviewCompletionSink",
    "RecordingReviewCompletionSink",
    "ReviewCompletionEvent",
    "ReviewCompletionSink",
]


@dataclass(frozen=True)
class ReviewCompletionEvent:
    """An immutable fact: one Layer-2 review artefact was written (FK-27 §27.5.5).

    Attributes:
        story_id: Story whose Layer-2 review completed.
        role: Mandatory reviewer role (``qa_review`` / ``semantic_review`` /
            ``doc_fidelity``) carried into the ``llm_call_complete`` payload so
            the ``guard.multi_llm`` per-role count matches (FK-27 §27.4.3).
        artifact_filename: The review artefact filename that was written
            (e.g. ``qa_review.json``), for forensic correlation.
    """

    story_id: str
    role: str
    artifact_filename: str


@runtime_checkable
class ReviewCompletionSink(Protocol):
    """Port receiving ``llm_call_complete`` facts after a review artefact write.

    The verify-system BC owns this port; the productive telemetry adapter is
    wired at the composition root. Keeping the sink behind a Protocol avoids a
    verify-system import of the telemetry BC.
    """

    def review_completed(self, event: ReviewCompletionEvent) -> None:
        """Record that a Layer-2 review artefact was written (FK-27 §27.5.5).

        Args:
            event: The completion fact (story, role, artefact filename).
        """
        ...


@dataclass(frozen=True)
class NullReviewCompletionSink:
    """No-op sink: drops review-completion events.

    Default for callers without a wired telemetry adapter (test paths,
    pre-integration). NOT a weakening of the guard: ``guard.multi_llm`` counts
    canonical ``llm_call_complete`` events, so a dropped emission leaves the
    count at 0 and the BLOCKING guard fails closed (NO ERROR BYPASSING).
    """

    def review_completed(self, event: ReviewCompletionEvent) -> None:
        """Drop the event (no-op).

        Args:
            event: The completion fact (ignored).
        """
        del event  # no-op sink intentionally ignores the event (S1172).


@dataclass(frozen=True)
class RecordingReviewCompletionSink:
    """In-memory sink collecting review-completion events for tests/diagnostics."""

    events: list[ReviewCompletionEvent]

    @classmethod
    def empty(cls) -> RecordingReviewCompletionSink:
        """Construct a sink with a fresh empty event list.

        Returns:
            A new recording sink.
        """
        return cls(events=[])

    def review_completed(self, event: ReviewCompletionEvent) -> None:
        """Append the event to the in-memory list.

        Args:
            event: The completion fact to record.
        """
        self.events.append(event)
