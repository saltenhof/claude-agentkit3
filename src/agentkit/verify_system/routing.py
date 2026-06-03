"""QA-Subflow layer routing.

Determines which QA layers to run for a given ``QaContext``.

Routing rules (normative source: ``concept/_meta/bc-cut-decisions.md
§QA-Subflow-Vertrag``):

- IMPLEMENTATION_INITIAL / IMPLEMENTATION_REMEDIATION:
  All four layers: Structural (1), LLM-Evaluator (2), Adversarial (3),
  Policy (4). Matches FK-27 §27.3 full 4-layer QA.

- EXPLORATION_INITIAL / EXPLORATION_REMEDIATION:
  Reduced layer set: LLM-Evaluator (2) + Policy (4). Design-review
  only; no structural or adversarial checks (BC-Cut: Exploration-Vertrag).

Quelle: AG3-026 §2.1.2, ``concept/_meta/bc-cut-decisions.md §QA-Subflow-Vertrag``
"""

from __future__ import annotations

from enum import StrEnum

from agentkit.core_types import QaContext


class QALayerKind(StrEnum):
    """Identifies a QA layer slot within the verify-system BC.

    Used by ``select_layers`` to produce an ordered tuple of layer
    identifiers. ``VerifySystem.run_qa_subflow`` maps these to the actual
    layer instances it holds via DI.

    Attributes:
        STRUCTURAL: Layer 1 -- deterministic structural checks.
        LLM_EVALUATOR: Layer 2 -- LLM-based code review.
        ADVERSARIAL: Layer 3 -- adversarial edge-case testing.
        SONARQUBE_GATE: Layer-1 deterministic SonarQube-Green-Gate
            (Trust A, blocking) sequenced AFTER the adversarial layer
            (FK-33 §33.6.3 / §33.8.3): every prior remediation changes
            production code and may introduce new violations, so the
            green gate is the final deterministic convergence step before
            the policy aggregator.
        POLICY: Layer 4 -- deterministic policy aggregation.
    """

    STRUCTURAL = "structural"
    LLM_EVALUATOR = "llm_evaluator"
    ADVERSARIAL = "adversarial"
    SONARQUBE_GATE = "sonarqube_gate"
    POLICY = "policy"


#: Full sequence for Implementation contexts (FK-27 §27.3, FK-33 §33.8.3).
#: ``sonarqube_gate`` is classificatory Layer 1 but sequenced AFTER the
#: adversarial layer and BEFORE policy aggregation.
_IMPLEMENTATION_LAYERS: tuple[QALayerKind, ...] = (
    QALayerKind.STRUCTURAL,
    QALayerKind.LLM_EVALUATOR,
    QALayerKind.ADVERSARIAL,
    QALayerKind.SONARQUBE_GATE,
    QALayerKind.POLICY,
)

#: Reduced layer set for Exploration contexts (BC-Cut: Exploration-Vertrag).
_EXPLORATION_LAYERS: tuple[QALayerKind, ...] = (
    QALayerKind.LLM_EVALUATOR,
    QALayerKind.POLICY,
)

#: Mapping from QaContext to the ordered layer-kind tuple.
_ROUTING_TABLE: dict[QaContext, tuple[QALayerKind, ...]] = {
    QaContext.IMPLEMENTATION_INITIAL: _IMPLEMENTATION_LAYERS,
    QaContext.IMPLEMENTATION_REMEDIATION: _IMPLEMENTATION_LAYERS,
    QaContext.EXPLORATION_INITIAL: _EXPLORATION_LAYERS,
    QaContext.EXPLORATION_REMEDIATION: _EXPLORATION_LAYERS,
}


def select_layers(qa_context: QaContext) -> tuple[QALayerKind, ...]:
    """Return the ordered tuple of layer kinds for the given QaContext.

    The returned tuple determines:
    - *which* layers the ``VerifySystem`` executes, and
    - *in what order* (position 0 runs first).

    Args:
        qa_context: The invocation context supplied by the pipeline.

    Returns:
        Ordered tuple of ``QALayerKind`` values.

    Raises:
        KeyError: If ``qa_context`` is not in the routing table. This
            cannot happen with a valid ``QaContext`` enum value, but
            is documented for completeness (fail-closed).
    """
    return _ROUTING_TABLE[qa_context]


__all__ = ["QALayerKind", "select_layers"]
