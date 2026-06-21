"""MandateClassification -- the exploration mandate classifier (FK-25 §25.4.1).

FK-25 §25.4.1 classifies each unresolved design decision into one of four
escalation classes, in the fail-closed check order *Klasse 1 -> 3 -> 4 -> 2*
("the most restrictive class first, so that no case is resolved as autonomous
too early"). The FIRST hit wins.

English class names / values (ARCH-55) and their FK-25 mapping
--------------------------------------------------------------
The FK-25 ``klasse_1..klasse_4`` German enum values violate the English mandate;
:class:`MandateClass` uses English member names AND values:

==================  ==========  =========================================
MandateClass        FK-25       meaning
==================  ==========  =========================================
``TRIVIAL``         Klasse 1*   no mandate block -> straight to review
``FINE_DESIGN``     Klasse 2    fine-design subprocess (FK-25 §25.5)
``SCOPE_EXPLOSION`` Klasse 3    scope explosion -> human story split
``IMPACT_ESCALATION`` Klasse 4  impact exceedance -> architecture review
==================  ==========  =========================================

\\* FK-25 Klasse 1 (domain_gap / normative_conflict) is a purely SEMANTIC,
LLM-judged escalation ("Klasse 1 ... consistently semantic assessments",
FK-25 §25.4.1) and is NOT derivable from the change-frame deterministically. The
deterministic classifier therefore cannot raise Klasse 1 from change-frame
signals alone; in the absence of a scope/impact/fine-design signal the decision
is the autonomous, non-blocking path -- modelled here as ``TRIVIAL`` (the
"straight to review, no mandate block" route, story AG3-047 handler integration).
The LLM-judged Klasse-1 detection is owned by the H2 reclassification
(FK-25 §25.4.3, a follow-up LLM step), not by this deterministic signal layer.

Check order (FK-25 §25.4.1, first hit wins)
-------------------------------------------
1. Klasse 1 -- domain gap / normative conflict (semantic; not derivable here);
3. Klasse 3 -- scope explosion (``ScopeExplosionDetector``, >= 2 HIGH);
4. Klasse 4 -- impact exceedance (``ImpactExceedanceChecker``, actual > declared);
2. Klasse 2 -- fine design (cross-method, normatively covered, unresolved);
else -> method-local / trivial -> ``TRIVIAL``.

The relative order 3-before-4-before-2 is preserved exactly. Both the scope and
the impact sub-checks always RUN (their results are carried in the result and
emitted as their own telemetry events, FK-25 §25.8) -- the order only decides
which class WINS.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agentkit.backend.exploration.mandate.impact_checker import ImpactExceedanceResult
from agentkit.backend.exploration.mandate.scope_detector import ScopeExplosionResult

if TYPE_CHECKING:
    from agentkit.backend.exploration.change_frame import ChangeFrame
    from agentkit.backend.exploration.mandate.impact_checker import ImpactExceedanceChecker
    from agentkit.backend.exploration.mandate.scope_detector import ScopeExplosionDetector
    from agentkit.backend.story_context_manager.story_model import ChangeImpact


class MandateClass(StrEnum):
    """The four mandate classes (FK-25 §25.3, English names/values, ARCH-55).

    Attributes:
        TRIVIAL: FK-25 Klasse 1 sense for the deterministic layer -- no mandate
            block; the decision is method-local / autonomous -> straight to the
            review (no extra step).
        FINE_DESIGN: FK-25 Klasse 2 -- a cross-method, normatively covered,
            unresolved technical decision -> fine-design subprocess (FK-25 §25.5).
        SCOPE_EXPLOSION: FK-25 Klasse 3 -- scope grew beyond the story scope ->
            escalate (human story-split decision, FK-25 §25.6.3).
        IMPACT_ESCALATION: FK-25 Klasse 4 -- actual impact exceeds the declared
            mandate -> escalate (architecture review, FK-25 §25.7.2).
    """

    TRIVIAL = "trivial"
    FINE_DESIGN = "fine_design"
    SCOPE_EXPLOSION = "scope_explosion"
    IMPACT_ESCALATION = "impact_escalation"


class MandateClassificationResult(BaseModel):
    """The classification outcome (FK-25 §25.4.1).

    Attributes:
        mandate_class: The winning class (first hit in order 1 -> 3 -> 4 -> 2).
        scope_explosion: The full scope-explosion sub-result (always computed;
            emitted as ``scope_explosion_check``, FK-25 §25.8).
        impact_exceedance: The full impact-exceedance sub-result (always
            computed; emitted as ``impact_exceedance_check``, FK-25 §25.8).
        decision_summary: A short, operator-facing English summary of the winning
            class (carried in the ``mandate_classification`` telemetry payload).
        run_design_challenge: Whether the optional Stage-2b design challenge must
            run for this class (mandate-gating, FK-25 §25.4.2 step G / story
            AG3-047). The escalating classes and the fine-design class warrant
            the adversarial challenge; a trivial decision does not.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mandate_class: MandateClass
    scope_explosion: ScopeExplosionResult
    impact_exceedance: ImpactExceedanceResult
    decision_summary: str
    run_design_challenge: bool


#: English operator-facing summaries per winning class (FK-25 §25.3 reactions).
_CLASS_SUMMARY: dict[MandateClass, str] = {
    MandateClass.SCOPE_EXPLOSION: (
        "scope explosion detected (>= 2 HIGH indicators): story exceeds its "
        "declared scope -- recommend story split (FK-25 §25.6.3)"
    ),
    MandateClass.IMPACT_ESCALATION: (
        "impact exceedance detected: actual change impact exceeds the declared "
        "mandate -- architecture review needed (FK-25 §25.7.2)"
    ),
    MandateClass.FINE_DESIGN: (
        "fine-design decision required: unresolved cross-method technical detail "
        "within the normative frame -- fine-design subprocess (FK-25 §25.5)"
    ),
    MandateClass.TRIVIAL: (
        "no mandate block: method-local decision within scope, impact and the "
        "normative frame -- proceed to exit-gate review (FK-25 §25.4.1)"
    ),
}

#: Classes for which the Stage-2b adversarial design challenge runs (mandate
#: gating, FK-25 §25.4.2 / story AG3-047). A trivial decision does not warrant
#: the extra adversarial pass; the escalating + fine-design classes do.
_DESIGN_CHALLENGE_CLASSES: frozenset[MandateClass] = frozenset({
    MandateClass.SCOPE_EXPLOSION,
    MandateClass.IMPACT_ESCALATION,
    MandateClass.FINE_DESIGN,
})


class MandateClassification:
    """Classify a change-frame into a mandate class (FK-25 §25.4.1)."""

    def __init__(
        self,
        scope_detector: ScopeExplosionDetector,
        impact_checker: ImpactExceedanceChecker,
    ) -> None:
        """Initialise the classifier.

        Args:
            scope_detector: The Klasse-3 scope-explosion detector (FK-25 §25.6).
            impact_checker: The Klasse-4 impact-exceedance checker (FK-25 §25.7).
        """
        self._scope_detector = scope_detector
        self._impact_checker = impact_checker

    def classify(
        self, change_frame: ChangeFrame, declared_impact: ChangeImpact
    ) -> MandateClassificationResult:
        """Classify the change-frame in the FK-25 §25.4.1 order (first hit wins).

        Both sub-checks ALWAYS run (their results are returned for telemetry,
        FK-25 §25.8); the check ORDER (3 -> 4 -> 2 after the non-derivable
        Klasse-1) only decides which class wins.

        Args:
            change_frame: The validated change-frame.
            declared_impact: The authoritative declared change impact (resolved
                by the caller via ``DeclaredImpactReader``; never defaulted).

        Returns:
            The :class:`MandateClassificationResult` with the winning class.
        """
        scope = self._scope_detector.detect(change_frame)
        impact = self._impact_checker.check(change_frame, declared_impact)

        # Order: 1 (not derivable here) -> 3 -> 4 -> 2 -> trivial. First hit wins.
        if scope.triggered:
            mandate_class = MandateClass.SCOPE_EXPLOSION
        elif impact.exceeded:
            mandate_class = MandateClass.IMPACT_ESCALATION
        elif self._is_fine_design(change_frame):
            mandate_class = MandateClass.FINE_DESIGN
        else:
            mandate_class = MandateClass.TRIVIAL

        return MandateClassificationResult(
            mandate_class=mandate_class,
            scope_explosion=scope,
            impact_exceedance=impact,
            decision_summary=_CLASS_SUMMARY[mandate_class],
            run_design_challenge=mandate_class in _DESIGN_CHALLENGE_CLASSES,
        )

    @staticmethod
    def _is_fine_design(change_frame: ChangeFrame) -> bool:
        """Whether the change-frame signals an unresolved fine-design decision.

        FK-25 §25.5 Klasse 2: an unresolved technical detail with cross-method
        effect that is covered by (not contradicting) the normative sources and
        needs no new domain knowledge. The deterministic, change-frame-derivable
        proxy is a non-empty ``open_points.approval_needed`` -- explicitly
        flagged points that still need a (design-level) decision within the
        frame. A frame with no such open point is method-local (trivial). The
        full semantic Klasse-2 detection is the H2 reclassification
        (FK-25 §25.4.3), a follow-up LLM step.

        Args:
            change_frame: The validated change-frame.

        Returns:
            ``True`` iff the frame carries at least one ``approval_needed`` open
            point (the fine-design signal).
        """
        return bool(change_frame.open_points.approval_needed)


__all__ = [
    "MandateClass",
    "MandateClassification",
    "MandateClassificationResult",
]
