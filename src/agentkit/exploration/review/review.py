"""ExplorationReview -- the three-stage exit-gate orchestrator (FK-23 §23.5).

:class:`ExplorationReview` is the orchestrator of the exploration exit-gate. It
runs the three stages in the concept-normative order (FK-23 §23.5 /
``formal.exploration.state-machine``):

1. **Stage 1 -- document fidelity** (:class:`DocFidelityChecker`, §23.5.1):
   binary. A FAIL is a hard architecture conflict -> ``overall_status =
   REJECTED`` and the gate STOPS (NO ERROR BYPASSING: there is no path to
   ``APPROVED`` without a Stage-1 PASS).
2. **Stage 2a -- design review** (:class:`DesignReviewRunner`, §23.5.2): bounded
   remediation loop (max 3). A FAIL at the round ceiling -> ``escalated`` (the
   story STAYS in exploration; ``overall_status = PENDING``, the handler maps
   this to ``HandlerResult.ESCALATED``). A non-escalated FAIL -> ``REJECTED``.
3. **Stage 2b -- design challenge** (:class:`DesignChallengeRunner`, §23.5.3):
   OPTIONAL; only run when wired in (mandate-gating is AG3-047). A FAIL ->
   ``REJECTED``.

Only when every required stage PASSES (and the optional Stage 2b, when run,
PASSES) is ``overall_status = APPROVED``. The gate is fail-closed throughout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agentkit.core_types import ExplorationGateStatus
from agentkit.exploration.review.design_challenge import DesignChallengeResult
from agentkit.exploration.review.design_review import DesignReviewResult
from agentkit.exploration.review.doc_fidelity import DocFidelityResult

if TYPE_CHECKING:
    from agentkit.artifacts import ArtifactManager
    from agentkit.exploration.change_frame import ChangeFrame
    from agentkit.exploration.review.design_challenge import DesignChallengeRunner
    from agentkit.exploration.review.design_review import DesignReviewRunner
    from agentkit.exploration.review.doc_fidelity import DocFidelityChecker


class ExplorationGateResult(BaseModel):
    """Aggregate result of the three-stage exploration exit-gate (FK-23 §23.5).

    Attributes:
        stage1_result: Stage 1 document-fidelity result (always present).
        stage2a_result: Stage 2a design-review result, or ``None`` when Stage 1
            FAILED (the gate stopped before Stage 2a, fail-closed).
        stage2b_result: Stage 2b design-challenge result, or ``None`` when the
            optional stage was not wired in / not reached.
        overall_status: The gate decision: ``APPROVED`` only when every required
            stage passed; ``REJECTED`` on a Stage-1 FAIL, a non-escalated
            Stage-2a FAIL or a Stage-2b FAIL; ``PENDING`` when Stage 2a escalated
            (the story stays in exploration, handler -> ``ESCALATED``).
        review_rounds: Number of Stage-2a design-review rounds run (0 when
            Stage 1 FAILED before Stage 2a).
        escalation_reason: The operator-facing recommended reaction when Stage 2a
            escalated (carried to ``HandlerResult.suggested_reaction``, AG3-044);
            ``None`` otherwise.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage1_result: DocFidelityResult
    stage2a_result: DesignReviewResult | None
    stage2b_result: DesignChallengeResult | None
    overall_status: ExplorationGateStatus
    review_rounds: int
    escalation_reason: str | None = None

    @property
    def is_escalated(self) -> bool:
        """Whether Stage 2a escalated (gate PENDING, story stays in exploration).

        Returns:
            ``True`` iff the wired Stage 2a result is ``escalated``.
        """
        return self.stage2a_result is not None and (
            self.stage2a_result.status == "escalated"
        )


class ExplorationReview:
    """Orchestrate the three-stage exploration exit-gate (FK-23 §23.5)."""

    def __init__(
        self,
        stage1_doc_fidelity: DocFidelityChecker,
        stage2a_design_review: DesignReviewRunner,
        stage2b_design_challenge: DesignChallengeRunner | None,
        artifact_manager: ArtifactManager,
    ) -> None:
        """Initialize the review orchestrator.

        Args:
            stage1_doc_fidelity: Stage 1 document-fidelity checker (§23.5.1).
            stage2a_design_review: Stage 2a design-review runner (§23.5.2).
            stage2b_design_challenge: Stage 2b design-challenge runner (§23.5.3),
                or ``None`` to skip the optional stage (AG3-046 wires ``None``;
                mandate-gated activation is AG3-047).
            artifact_manager: The artifact write surface (held for the gate's
                aggregate-artifact persistence; the per-stage results are
                persisted by each stage's injected sink).
        """
        self._stage1 = stage1_doc_fidelity
        self._stage2a = stage2a_design_review
        self._stage2b = stage2b_design_challenge
        self._artifact_manager = artifact_manager

    def run(
        self, change_frame: ChangeFrame, *, run_design_challenge: bool = True
    ) -> ExplorationGateResult:
        """Run the three stages in the concept-normative order (FK-23 §23.5).

        Args:
            change_frame: The validated worker change-frame (FK-23 §23.4).
            run_design_challenge: Mandate-gating for the OPTIONAL Stage-2b design
                challenge (FK-23 §23.5.3 / FK-25 §25.4.2 step G; AG3-047). When
                ``True`` (the default -- preserves the prior behaviour) and a
                Stage-2b runner is wired, Stage 2b runs. When ``False`` the
                adversarial challenge is skipped for this run regardless of
                wiring (the mandate class did not warrant it). The classifier
                computes this flag from
                :attr:`~agentkit.exploration.mandate.classification.MandateClassificationResult.run_design_challenge`.

        Returns:
            The aggregate :class:`ExplorationGateResult`. ``overall_status`` is
            ``APPROVED`` only after a Stage-1 PASS, a Stage-2a PASS and (when
            run) a Stage-2b PASS.

        Raises:
            StructuredEvaluatorError: On an unparseable / schema-violating LLM
                response in any stage (propagated fail-closed).
            LlmClientError: If the LLM transport fails (propagated fail-closed).
        """
        # --- Stage 1: document fidelity (binary) --------------------------
        stage1 = self._stage1.check(change_frame)
        if stage1.status != "pass":
            # FK-23 §23.5 (a): Stage-1 FAIL -> REJECTED, gate stops. There is NO
            # path to APPROVED without a Stage-1 PASS (NO ERROR BYPASSING).
            return ExplorationGateResult(
                stage1_result=stage1,
                stage2a_result=None,
                stage2b_result=None,
                overall_status=ExplorationGateStatus.REJECTED,
                review_rounds=0,
            )

        # --- Stage 2a: design review (bounded remediation loop) -----------
        stage2a = self._stage2a.run(change_frame, list(stage1.findings))
        if stage2a.status == "escalated":
            # FK-23 §23.5.2 round-limit -> ESCALATED. The story STAYS in the
            # exploration phase (gate PENDING, not REJECTED); the handler maps
            # this to HandlerResult.ESCALATED with the suggested_reaction.
            return ExplorationGateResult(
                stage1_result=stage1,
                stage2a_result=stage2a,
                stage2b_result=None,
                overall_status=ExplorationGateStatus.PENDING,
                review_rounds=stage2a.review_rounds,
                escalation_reason=stage2a.suggested_reaction,
            )
        if stage2a.status != "pass":
            return ExplorationGateResult(
                stage1_result=stage1,
                stage2a_result=stage2a,
                stage2b_result=None,
                overall_status=ExplorationGateStatus.REJECTED,
                review_rounds=stage2a.review_rounds,
            )

        # --- Stage 2b: design challenge (optional, mandate-gated) ---------
        # FK-25 §25.4.2 / AG3-047: the adversarial challenge runs only when the
        # mandate class warrants it (``run_design_challenge``) AND a runner is
        # wired. A gated-off challenge is NOT a skip of a required stage -- it is
        # the concept-normative conditional Stage G (FK-23 §23.5.3 "OPTIONAL").
        stage2b: DesignChallengeResult | None = None
        if run_design_challenge and self._stage2b is not None:
            stage2b = self._stage2b.run(change_frame, (stage1, stage2a))
            if stage2b.status != "pass":
                return ExplorationGateResult(
                    stage1_result=stage1,
                    stage2a_result=stage2a,
                    stage2b_result=stage2b,
                    overall_status=ExplorationGateStatus.REJECTED,
                    review_rounds=stage2a.review_rounds,
                )

        # --- All required stages passed -> APPROVED -----------------------
        return ExplorationGateResult(
            stage1_result=stage1,
            stage2a_result=stage2a,
            stage2b_result=stage2b,
            overall_status=ExplorationGateStatus.APPROVED,
            review_rounds=stage2a.review_rounds,
        )


__all__ = ["ExplorationGateResult", "ExplorationReview"]
