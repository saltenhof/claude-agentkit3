"""Stage 2a of the exploration exit-gate: design review (FK-23 §23.5.2).

Stage 2a is the design-review with a BOUNDED remediation loop (FK-23 §23.5.2,
max 3 rounds). Each round runs the Layer-2
:class:`~agentkit.backend.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`
in the ``SEMANTIC_REVIEW`` role (the systemic-adequacy / design-quality check,
FK-34 §34.2.3 / FK-11 §11.5.1 ``Exploration: Design-Review``). The loop
ceiling and escalation decision reuse the AG3-041
:class:`~agentkit.backend.verify_system.remediation.loop_counter.RemediationLoopController`
(``max_feedback_rounds=3``) -- the ONE bounded-loop decision SSOT, never a
re-implemented ``round >= max`` check (FIX THE MODEL).

Loop semantics (FK-23 §23.5.2 / FK-27 §27.2.2):

* verdict ``PASS``                              -> ``status="pass"``;
* verdict ``FAIL`` while ``round < max`` AND a revised frame is available
                                                -> next round (remediation);
* verdict ``FAIL`` while ``round < max`` AND NO reviser is wired
                                                -> ``status="escalated"`` (fail
  CLOSED: the same, already-failed frame is NEVER re-evaluated -- a
  non-deterministic FAIL-then-PASS over the IDENTICAL frame must not pass the
  gate, NO ERROR BYPASSING);
* verdict ``FAIL`` at ``round >= max``          -> ``status="escalated"`` (the
  story stays in the exploration phase, operator intervention; FK-23 §23.5 (c)
  round-limit, AG3-046 §2.1.6).

Re-drafting boundary (story.md §2.2 / FK-23 §23.5.2): a remediation round only
makes sense against a RE-DRAFTED change-frame -- evaluating the unchanged frame
again would let a flaky LLM flip FAIL->PASS without any actual remediation
(silent bypass). The next-round frame is therefore supplied by an injected
:class:`ChangeFrameReviser` port. The worker-driven re-drafting that implements
this port is the follow-up story AG3-054; in the AG3-046 state no reviser is
wired, so a FAIL fails CLOSED to escalation immediately. When a reviser IS wired
and yields a genuinely revised frame, the loop continues per FK-23 §23.5.2 and
the prior round's findings are passed into the evaluator so the
``finding_resolution_*`` checks become mandatory before a later PASS is accepted
(FK-34 §34.9). The escalation guarantee holds regardless: a FAIL at the ceiling
always escalates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from agentkit.backend.artifacts.reference import ArtifactReference
from agentkit.backend.core_types import PolicyVerdict
from agentkit.backend.exploration.review.bundle import build_change_frame_bundle
from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
    LlmVerdict,
    ReviewerRole,
)
from agentkit.backend.verify_system.protocols import Finding
from agentkit.backend.verify_system.qa_cycle.lifecycle import QaCycleState
from agentkit.backend.verify_system.remediation.loop_counter import (
    DEFAULT_MAX_FEEDBACK_ROUNDS,
    RemediationDecision,
    RemediationLoopController,
)

if TYPE_CHECKING:
    from agentkit.backend.exploration.change_frame import ChangeFrame
    from agentkit.backend.exploration.review.persistence import ReviewResultSink
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluator,
    )

#: Fixed placeholder identity for the per-round loop snapshot. Only ``round``
#: feeds ``RemediationLoopController.check_and_advance``; the QA-cycle identity
#: fields (id / epoch / fingerprint) are not consulted for the design-review
#: loop decision, so a deterministic placeholder is used (no fabricated
#: fingerprint masquerading as a real QA-cycle artifact).
_LOOP_SNAPSHOT_ID = "design-review0"
_LOOP_SNAPSHOT_FINGERPRINT = (
    "0000000000000000000000000000000000000000000000000000000000000000"
)

#: Prefix marking a synthetic resolution-STATUS finding (FK-34 §34.9.4); such a
#: finding reports a PRIOR finding's resolution and is not itself a resolvable
#: subject, so it is excluded from the ``previous_findings`` carried into the
#: next round (would otherwise nest the ``finding_resolution_`` prefix). Mirrors
#: the StructuredEvaluator wire prefix without importing its private constant.
_RESOLUTION_FINDING_PREFIX = "finding_resolution_"


def _design_findings(findings: tuple[Finding, ...]) -> list[Finding]:
    """Return the design-quality findings (drop synthetic resolution findings).

    Args:
        findings: All findings produced by a round.

    Returns:
        The findings whose ``check`` is a real design check, i.e. not a
        ``finding_resolution_*`` resolution-status record (FK-34 §34.9.4).
    """
    return [
        f for f in findings if not f.check.startswith(_RESOLUTION_FINDING_PREFIX)
    ]


@runtime_checkable
class ChangeFrameReviser(Protocol):
    """Port supplying a RE-DRAFTED change-frame for the next remediation round.

    FK-23 §23.5.2 makes a design-review remediation round a re-evaluation of a
    *revised* change-frame, not a re-run over the identical (already-failed)
    frame. This port is the seam through which the next-round frame is produced
    from the failing frame plus the round's findings. The worker-driven
    re-drafting that implements it is the follow-up story AG3-054; until then no
    reviser is wired (``DesignReviewRunner(..., reviser=None)``), so a FAIL fails
    CLOSED to escalation rather than re-evaluating the same frame.
    """

    def revise(
        self,
        change_frame: ChangeFrame,
        findings: tuple[Finding, ...],
        *,
        next_round: int,
    ) -> ChangeFrame | None:
        """Produce the next-round revised change-frame, or ``None``.

        Args:
            change_frame: The change-frame that just FAILed design review.
            findings: The blocking findings of the round that just failed
                (the remediation work order, FK-34 §34.9).
            next_round: The 1-based round the revised frame is destined for
                (``>= 2``).

        Returns:
            A genuinely revised :class:`ChangeFrame` to evaluate next, or
            ``None`` when no revision can be produced (the runner then fails
            CLOSED to escalation; no same-frame re-evaluation).
        """
        ...


class DesignReviewResult(BaseModel):
    """Result of Stage 2a design review (FK-23 §23.5.2).

    Attributes:
        status: ``"pass"`` on an evaluator PASS; ``"fail"`` when the loop ended
            non-escalated without a PASS (defensive; the loop normally only
            terminates on PASS or escalation); ``"escalated"`` when a FAIL hit
            the round ceiling (FK-23 §23.5 (c)).
        review_rounds: Number of design-review rounds actually run (>= 1).
        findings_per_round: The findings produced in each round (one inner tuple
            per round, in order).
        final_evaluator_result_ref: Reference to the persisted last-round
            evaluator-result QA artifact (real audit anchor, never fabricated).
        suggested_reaction: On escalation, the human-readable recommended
            reaction carried up to ``HandlerResult.suggested_reaction``
            (AG3-044); ``None`` otherwise.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["pass", "fail", "escalated"]
    review_rounds: int
    findings_per_round: tuple[tuple[Finding, ...], ...]
    final_evaluator_result_ref: ArtifactReference
    suggested_reaction: str | None = None


class DesignReviewRunner:
    """Stage 2a design-review runner with bounded remediation loop (FK-23 §23.5.2)."""

    def __init__(
        self,
        structured_evaluator: StructuredEvaluator,
        result_sink: ReviewResultSink,
        max_rounds: int = DEFAULT_MAX_FEEDBACK_ROUNDS,
        *,
        reviser: ChangeFrameReviser | None = None,
    ) -> None:
        """Initialize the runner.

        Args:
            structured_evaluator: The Layer-2 evaluator (DI; LLM-boundary seam).
                Called with :attr:`ReviewerRole.SEMANTIC_REVIEW`.
            result_sink: Persistence port for the per-round evaluator result.
            max_rounds: Loop ceiling (FK-03 §3.4.2 default 3). Drives the reused
                :class:`RemediationLoopController` (>= 1, fail-closed).
            reviser: Optional re-draft source (FK-23 §23.5.2). When ``None`` (the
                AG3-046 state; worker re-drafting is AG3-054) a FAIL below the
                ceiling escalates immediately instead of re-evaluating the same
                frame (fail CLOSED, NO ERROR BYPASSING). When wired, it supplies
                the revised next-round frame so a remediation round evaluates a
                genuinely changed frame.
        """
        self._evaluator = structured_evaluator
        self._sink = result_sink
        self._controller = RemediationLoopController(max_feedback_rounds=max_rounds)
        self._reviser = reviser

    def run(
        self,
        change_frame: ChangeFrame,
        doc_fidelity_findings: list[Finding],
    ) -> DesignReviewResult:
        """Run the bounded design-review remediation loop.

        Args:
            change_frame: The validated worker change-frame (FK-23 §23.4).
            doc_fidelity_findings: Stage 1 findings carried into the first
                round's remediation context (FK-34 §34.9).

        Returns:
            A :class:`DesignReviewResult`: ``"pass"`` on a PASS, ``"escalated"``
            when a FAIL hits the round ceiling OR when a FAIL below the ceiling
            has no re-draft source (fail CLOSED; FK-23 §23.5.2).

        Raises:
            StructuredEvaluatorError: On an unparseable / schema-violating LLM
                response (propagated fail-closed).
            LlmClientError: If the LLM transport fails (propagated fail-closed).
        """
        findings_per_round: list[tuple[Finding, ...]] = []
        # The frame under review in the current round. On a remediation round it
        # is the reviser's RE-DRAFTED frame, never the unchanged previous one.
        current_frame = change_frame
        # Findings carried into the next round. Round 1 carries the Stage-1
        # doc-fidelity findings as context; round 2+ carries the prior design-
        # review findings, which on a REVISED frame are also passed to the
        # evaluator as ``previous_findings`` so the finding_resolution_* checks
        # become mandatory before a later PASS is accepted (FK-34 §34.9).
        carried: list[Finding] = list(doc_fidelity_findings)
        # ``previous_findings`` for the evaluator: ``None`` in round 1 (initial
        # evaluation, no resolution contract). Set only once a revised frame is
        # produced, so resolution checks are mandated exactly on the revised
        # path (FK-34 §34.9), never against an unchanged frame.
        resolution_findings: list[Finding] | None = None
        last_ref: ArtifactReference | None = None
        # Every frame dump already evaluated (and failed) this run. A reviser must
        # never re-surface ANY previously-failed frame -- not only the immediately
        # prior one (e.g. an A->B->A cycle) -- or a non-deterministic evaluator
        # could flip a previously-failed frame to PASS (NO ERROR BYPASSING).
        seen_dumps: set[str] = set()
        round_no = 0
        while True:
            round_no += 1
            seen_dumps.add(current_frame.model_dump_json())
            bundle = build_change_frame_bundle(
                current_frame,
                review_round=round_no,
                previous_findings=carried or None,
            )
            result = self._evaluator.evaluate(
                role=ReviewerRole.SEMANTIC_REVIEW,
                bundle=bundle,
                previous_findings=resolution_findings,
                qa_cycle_round=round_no,
            )
            last_ref = self._sink.persist(
                change_frame=current_frame,
                stage=ReviewerRole.SEMANTIC_REVIEW.value,
                review_round=round_no,
                evaluator_result=result,
            )
            findings_per_round.append(result.findings)
            decision = self._controller.check_and_advance(
                _loop_snapshot(round_no), _verdict_to_policy(result.verdict)
            )
            if decision is RemediationDecision.CONTINUE_TO_CLOSURE:
                return _result(
                    "pass", round_no, findings_per_round, last_ref, None
                )
            if decision is RemediationDecision.ESCALATE:
                return _result(
                    "escalated",
                    round_no,
                    findings_per_round,
                    last_ref,
                    _escalation_reason(round_no, result.findings),
                )
            # CONTINUE_REMEDIATION: a remediation round requires a RE-DRAFTED
            # frame. Without a reviser (AG3-046 state, re-drafting is AG3-054) we
            # fail CLOSED to escalation rather than re-evaluating the identical,
            # already-failed frame (NO ERROR BYPASSING: no same-frame flip to
            # PASS).
            revised = (
                self._reviser.revise(
                    current_frame, result.findings, next_round=round_no + 1
                )
                if self._reviser is not None
                else None
            )
            if revised is None:
                return _result(
                    "escalated",
                    round_no,
                    findings_per_round,
                    last_ref,
                    _no_reviser_reason(round_no, result.findings),
                )
            if revised.model_dump_json() in seen_dumps:
                # Defense against a miswired reviser: a "revision" that re-surfaces
                # ANY already-evaluated-and-failed frame -- the immediately prior one
                # OR an earlier one (e.g. an A->B->A cycle) -- is no revision. Re-
                # evaluating it could flip a previously-failed frame to PASS, re-
                # opening the NO-ERROR-BYPASSING hole, so fail closed.
                return _result(
                    "escalated",
                    round_no,
                    findings_per_round,
                    last_ref,
                    (
                        f"Stage-2a design review FAILED in round {round_no} and the "
                        "reviser returned a change-frame already evaluated and failed "
                        "this run; it cannot remediate the findings -- fail-closed to "
                        "escalation (FK-23 §23.5.2)."
                    ),
                )
            # A genuinely revised frame: continue the loop, carry this round's
            # design findings forward and mandate their resolution on the revised
            # frame. Only the design-quality findings are carried as
            # ``previous_findings``: the synthetic resolution-status findings
            # (FK-34 §34.9.4) describe a PRIOR finding's resolution and are not
            # themselves resolvable subjects -- re-encoding them as a new
            # ``finding_resolution_*`` id would nest the prefix and break the
            # canonical ``layer:check`` key (fail-closed). The reviewer still
            # sees the full round context via ``carried``.
            current_frame = revised
            design_findings = _design_findings(result.findings)
            carried = list(result.findings)
            resolution_findings = design_findings


def _verdict_to_policy(verdict: LlmVerdict) -> PolicyVerdict:
    """Map an LLM verdict onto the policy verdict the loop controller expects.

    Stage 2a is a blocking stage: only a clean ``PASS`` continues; ``FAIL`` and
    ``PASS_WITH_CONCERNS`` both count as a non-pass round (fail-closed, no
    concern softening at the gate).

    Args:
        verdict: The evaluator verdict.

    Returns:
        ``PolicyVerdict.PASS`` only for ``LlmVerdict.PASS``; else ``FAIL``.
    """
    return PolicyVerdict.PASS if verdict is LlmVerdict.PASS else PolicyVerdict.FAIL


def _loop_snapshot(round_no: int) -> QaCycleState:
    """Build the per-round snapshot the loop controller reads.

    Only ``round`` is consulted by
    :meth:`RemediationLoopController.check_and_advance`; the QA-cycle identity
    fields are deterministic placeholders (this is the design-review loop, not a
    QA cycle -- no fabricated QA-cycle fingerprint).

    Args:
        round_no: The 1-based round just completed.

    Returns:
        A :class:`QaCycleState` carrying ``round=round_no``.
    """
    return QaCycleState(
        qa_cycle_id=_LOOP_SNAPSHOT_ID,
        round=round_no,
        epoch=round_no,
        evidence_epoch=datetime.now(tz=UTC),
        evidence_fingerprint=_LOOP_SNAPSHOT_FINGERPRINT,
    )


def _escalation_reason(round_no: int, findings: tuple[Finding, ...]) -> str:
    """Build the human-readable escalation reaction (AG3-044 suggested_reaction).

    Args:
        round_no: The round at which the loop hit the ceiling.
        findings: The last round's blocking findings.

    Returns:
        A concise operator-facing reason string.
    """
    messages = "; ".join(f.message for f in findings) or "design review FAIL"
    return (
        f"Exploration design-review (Stage 2a) escalated after round {round_no} "
        f"(round limit reached, FK-23 §23.5.2). Operator intervention required "
        f"to re-draft the change-frame or relax constraints. Findings: {messages}"
    )


def _no_reviser_reason(round_no: int, findings: tuple[Finding, ...]) -> str:
    """Build the escalation reaction for a FAIL with no re-draft source.

    Fail-CLOSED case (FK-23 §23.5.2): the design review FAILed below the round
    ceiling but no :class:`ChangeFrameReviser` is wired, so there is no revised
    change-frame to evaluate. Re-running the identical frame would risk a flaky
    FAIL->PASS flip with no actual remediation, so the gate escalates instead.

    Args:
        round_no: The round at which the FAIL occurred (no reviser available).
        findings: The round's blocking findings.

    Returns:
        A concise operator-facing reason string.
    """
    messages = "; ".join(f.message for f in findings) or "design review FAIL"
    return (
        f"Exploration design-review (Stage 2a) escalated after round {round_no} "
        f"(FAIL with no re-draft source, FK-23 §23.5.2). The change-frame must "
        f"be re-drafted before re-evaluation (worker re-drafting: AG3-054); the "
        f"unchanged frame is not re-evaluated (NO ERROR BYPASSING). Findings: "
        f"{messages}"
    )


def _result(
    status: Literal["pass", "fail", "escalated"],
    review_rounds: int,
    findings_per_round: list[tuple[Finding, ...]],
    final_ref: ArtifactReference,
    suggested_reaction: str | None,
) -> DesignReviewResult:
    """Assemble a frozen :class:`DesignReviewResult`."""
    return DesignReviewResult(
        status=status,
        review_rounds=review_rounds,
        findings_per_round=tuple(findings_per_round),
        final_evaluator_result_ref=final_ref,
        suggested_reaction=suggested_reaction,
    )


__all__ = ["ChangeFrameReviser", "DesignReviewResult", "DesignReviewRunner"]
