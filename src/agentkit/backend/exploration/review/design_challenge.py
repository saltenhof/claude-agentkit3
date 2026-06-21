"""Stage 2b of the exploration exit-gate: design challenge (FK-23 §23.5.3).

Stage 2b is the OPTIONAL third gate stage (FK-23 §23.5.3): an adversarial
weakness-analysis of the change-frame, run only when the story mandate calls for
it. This module PROVIDES the runner class; the ACTIVATION logic (which mandate
classes trigger the challenge) is deferred to AG3-047 (MandateClassification) --
this story deliberately does NOT wire activation (story.md §2.1.4 / AC5).

.. warning::

   PLACEHOLDER ADVERSARIAL CHALLENGE (pending AG3-047). This runner is NOT a
   finished adversarial design-challenge and is NOT wired in production (AG3-046
   wires Stage 2b as ``None``). It reuses the systemic-adequacy
   ``SEMANTIC_REVIEW`` role as a stand-in for a dedicated adversarial
   ``design_challenge`` role/template (FK-11 §11.5.1), which is the AG3-047
   follow-up. Do not read its PASS as a real adversarial clearance.

Like the other stages it reuses the Layer-2
:class:`~agentkit.backend.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`.
The verify-system evaluator exposes three roles (``QA_REVIEW`` /
``SEMANTIC_REVIEW`` / ``DOC_FIDELITY``); the design-challenge PLACEHOLDER maps to
the systemic-adequacy ``SEMANTIC_REVIEW`` role (the closest existing
design-quality / weakness role, FK-34 §34.2.3). A dedicated ``design_challenge``
role/template (FK-11 §11.5.1) is the AG3-047 follow-up; introducing it now would
be a second, unused evaluator surface (ZERO DEBT: provide the class, not a
half-wired role).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from agentkit.backend.artifacts.reference import ArtifactReference
from agentkit.backend.exploration.review.bundle import build_change_frame_bundle
from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
    LlmVerdict,
    ReviewerRole,
)

if TYPE_CHECKING:
    from agentkit.backend.exploration.change_frame import ChangeFrame
    from agentkit.backend.exploration.review.design_review import DesignReviewResult
    from agentkit.backend.exploration.review.doc_fidelity import DocFidelityResult
    from agentkit.backend.exploration.review.persistence import ReviewResultSink
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluator,
    )
    from agentkit.backend.verify_system.protocols import Finding


def _collect_prior_findings(
    prior_results: tuple[DocFidelityResult, DesignReviewResult],
) -> list[Finding]:
    """Flatten the Stage 1 + Stage 2a findings into one ordered list.

    PLACEHOLDER context helper (pending AG3-047): the doc-fidelity findings and
    every design-review round's findings, in order, so the challenge bundle is
    coherent with what the earlier stages surfaced.

    Args:
        prior_results: The ``(doc_fidelity, design_review)`` results.

    Returns:
        The combined findings (may be empty when both stages were clean).
    """
    doc_fidelity, design_review = prior_results
    collected: list[Finding] = list(doc_fidelity.findings)
    for round_findings in design_review.findings_per_round:
        collected.extend(round_findings)
    return collected

#: Stage wire-id for the design-challenge persistence (matches the typed
#: ``ExplorationGateStage.DESIGN_CHALLENGE`` value without importing the DSL into
#: the review core).
_DESIGN_CHALLENGE_STAGE = "design_challenge"


class DesignChallengeResult(BaseModel):
    """Result of Stage 2b design challenge (FK-23 §23.5.3).

    Attributes:
        status: ``"pass"`` on an evaluator PASS; ``"fail"`` otherwise.
        challenge_summary: One-line summary of the challenge outcome.
        addressed_issues: The check-ids / messages the challenge raised.
        evaluator_result_ref: Reference to the persisted evaluator-result QA
            artifact (real audit anchor, never fabricated).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["pass", "fail"]
    challenge_summary: str
    addressed_issues: tuple[str, ...]
    evaluator_result_ref: ArtifactReference


class DesignChallengeRunner:
    """Stage 2b design-challenge runner -- PLACEHOLDER pending AG3-047 (FK-23 §23.5.3).

    .. warning::

       This is a PLACEHOLDER, not a finished adversarial challenge. It runs the
       ``SEMANTIC_REVIEW`` role (a design-quality evaluation) as a stand-in for a
       dedicated adversarial ``design_challenge`` role/template, which is the
       AG3-047 follow-up (FK-11 §11.5.1). Its PASS therefore does NOT certify
       that an adversarial weakness-analysis was performed.

    Provided per story.md §2.1.4; ACTIVATION (mandate-gating) is also deferred to
    AG3-047. ``ExplorationReview`` only invokes this runner when it is wired in
    (``stage2b_design_challenge is not None``); AG3-046 wires it as ``None``, so
    the placeholder never runs in production.
    """

    def __init__(
        self,
        structured_evaluator: StructuredEvaluator,
        result_sink: ReviewResultSink,
    ) -> None:
        """Initialize the runner.

        Args:
            structured_evaluator: The Layer-2 evaluator (DI; LLM-boundary seam).
            result_sink: Persistence port for the evaluator result.
        """
        self._evaluator = structured_evaluator
        self._sink = result_sink

    def run(
        self,
        change_frame: ChangeFrame,
        prior_results: tuple[DocFidelityResult, DesignReviewResult],
    ) -> DesignChallengeResult:
        """Run the design challenge against the change-frame.

        Args:
            change_frame: The validated worker change-frame (FK-23 §23.4).
            prior_results: The Stage 1 + Stage 2a results (challenge context).

        Returns:
            A :class:`DesignChallengeResult` (binary pass/fail).

        Raises:
            StructuredEvaluatorError: On an unparseable / schema-violating LLM
                response (propagated fail-closed).
            LlmClientError: If the LLM transport fails (propagated fail-closed).
        """
        # PLACEHOLDER coherence (pending AG3-047): fold the prior stages' findings
        # into the bundle CONTEXT so the challenge at least sees what doc-fidelity
        # and design-review surfaced, rather than discarding them. This is bundle
        # context only -- ``qa_cycle_round=1`` keeps it a fresh (non-remediation)
        # evaluation, so no finding_resolution_* contract is mandated. The
        # dedicated adversarial role/prompt that genuinely consumes this context
        # is the AG3-047 follow-up.
        prior_findings = _collect_prior_findings(prior_results)
        bundle = build_change_frame_bundle(
            change_frame,
            review_round=1,
            previous_findings=prior_findings or None,
        )
        result = self._evaluator.evaluate(
            role=ReviewerRole.SEMANTIC_REVIEW,
            bundle=bundle,
            previous_findings=None,
            qa_cycle_round=1,
        )
        ref = self._sink.persist(
            change_frame=change_frame,
            stage=_DESIGN_CHALLENGE_STAGE,
            review_round=1,
            evaluator_result=result,
        )
        status: Literal["pass", "fail"] = (
            "pass" if result.verdict is LlmVerdict.PASS else "fail"
        )
        addressed = tuple(f.message for f in result.findings)
        summary = (
            "design challenge passed (no weaknesses surfaced)"
            if status == "pass"
            else f"design challenge raised {len(addressed)} weakness(es)"
        )
        return DesignChallengeResult(
            status=status,
            challenge_summary=summary,
            addressed_issues=addressed,
            evaluator_result_ref=ref,
        )


__all__ = ["DesignChallengeResult", "DesignChallengeRunner"]
