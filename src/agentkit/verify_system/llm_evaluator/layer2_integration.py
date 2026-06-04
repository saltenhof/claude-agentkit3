"""Layer-2 LLM-runner integration glue (FK-27 §27.5 / story.md §2.1.7).

Bridges the LLM-evaluation runner (:class:`ParallelEvalRunner`) into the
``VerifySystem`` QA-subflow: it builds the :class:`ReviewBundle` from the
``Layer2ReviewInput`` and maps each per-role
:class:`StructuredEvaluatorResult` to a verify-system :class:`LayerResult` (in
the canonical ``qa_review``, ``semantic_review``, ``doc_fidelity`` order so the
results align with ``_LAYER_2_SPECS``).

Aggregation follows FK-34 §34.2.5: a role's ``LayerResult.passed`` is ``False``
iff its verdict is ``FAIL`` (a single FAIL blocks); ``PASS_WITH_CONCERNS`` does
not block. The findings are carried through verbatim from the evaluator so the
policy engine and the adversarial layer see them (FK-05-166).

Quelle:
  - FK-27 §27.5.1 -- drei parallele Bewertungen, Layer-2-Slot
  - FK-34 §34.2.5 -- Aggregation (ein FAIL blockiert)
  - story.md §2.1.7 -- VerifySystem-Integration
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.verify_system.llm_evaluator.bundle import build_review_bundle
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    LlmVerdict,
    ReviewerRole,
)
from agentkit.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
    TrustClass,
)
from agentkit.verify_system.remediation.finding_resolution import (
    LLM_RESOLUTION_METADATA_KEY,
    serialize_resolution_map,
)

if TYPE_CHECKING:
    from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput
    from agentkit.verify_system.llm_evaluator.parallel_runner import ParallelEvalRunner
    from agentkit.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluatorResult,
    )

logger = logging.getLogger(__name__)

#: Canonical Layer-2 role order; MUST match ``_artifact_specs.LAYER_2_SPECS``.
_ROLE_ORDER: tuple[ReviewerRole, ...] = (
    ReviewerRole.QA_REVIEW,
    ReviewerRole.SEMANTIC_REVIEW,
    ReviewerRole.DOC_FIDELITY,
)


def run_layer2_llm(
    runner: ParallelEvalRunner,
    review_input: Layer2ReviewInput,
    *,
    story_id: str,
    qa_cycle_round: int,
    previous_findings: tuple[Finding, ...],
) -> tuple[LayerResult, LayerResult, LayerResult]:
    """Run the three-role LLM Layer-2 and map results to LayerResults.

    Args:
        runner: The configured :class:`ParallelEvalRunner`.
        review_input: The four FK-27 §27.5.2 text inputs.
        story_id: Story display-ID (embedded into the bundle).
        qa_cycle_round: 1-based QA-cycle round (``> 1`` => remediation).
        previous_findings: Prior-round findings for the remediation prompt
            section (DK-04 §4.6); empty in the initial round.

    Returns:
        Three :class:`LayerResult` instances in the canonical role order
        (qa_review, semantic_review, doc_fidelity), aligned with
        ``_LAYER_2_SPECS``.

    Raises:
        ParallelEvalError: If any role's evaluation fails (fail-closed,
            propagated from the runner).
    """
    prev_list = list(previous_findings) if previous_findings else None
    bundle = build_review_bundle(
        review_input,
        story_id=story_id,
        qa_cycle_round=qa_cycle_round,
        previous_findings=prev_list,
    )
    results = runner.run(bundle, prev_list, qa_cycle_round)
    return tuple(  # type: ignore[return-value]  # exactly three roles, fixed order
        _to_layer_result(role, results[role]) for role in _ROLE_ORDER
    )


def run_layer2_llm_failclosed(
    runner: ParallelEvalRunner,
    review_input: Layer2ReviewInput,
    *,
    story_id: str,
    qa_cycle_round: int,
    previous_findings: tuple[Finding, ...],
) -> tuple[LayerResult, LayerResult, LayerResult]:
    """Run the LLM Layer-2 and convert any runner failure to BLOCKING results.

    Wraps :func:`run_layer2_llm` with the fail-closed contract: a runner
    failure (LLM transport / schema violation) is NOT propagated as a crash but
    mapped to three BLOCKING ``LayerResult`` (one per role) so the policy engine
    yields a definitive FAIL -- Layer 2 is never skipped (NO ERROR BYPASSING,
    FK-34 §34.5.1).

    Args:
        runner: The wired :class:`ParallelEvalRunner`.
        review_input: The four FK-27 §27.5.2 text inputs.
        story_id: Story display-ID.
        qa_cycle_round: 1-based QA-cycle round.
        previous_findings: Prior-round findings (remediation context).

    Returns:
        Three :class:`LayerResult` in canonical role order; all BLOCKING on a
        runner failure.
    """
    try:
        return run_layer2_llm(
            runner,
            review_input,
            story_id=story_id,
            qa_cycle_round=qa_cycle_round,
            previous_findings=previous_findings,
        )
    except Exception as exc:  # noqa: BLE001 -- fail-closed: any failure blocks
        error_msg = f"Layer 2 LLM evaluation failed: {type(exc).__name__}: {exc}"
        logger.error(error_msg, exc_info=exc)
        return (
            _blocking_result("qa_review", error_msg),
            _blocking_result("semantic_review", error_msg),
            _blocking_result("doc_fidelity", error_msg),
        )


def blocking_layer2_results(
    message: str,
) -> tuple[LayerResult, LayerResult, LayerResult]:
    """Return three BLOCKING Layer-2 ``LayerResult`` (one per role), fail-closed.

    Used when Layer 2 must run but cannot (FK-27 §27.5 "Reviews finden IMMER
    statt"): e.g. an LLM client is wired but the run ``StoryContext`` is
    unresolvable. Each role yields a BLOCKING SYSTEM finding so the policy
    engine produces a definitive FAIL -- never a silent skip or stub fallback
    (NO ERROR BYPASSING).

    Args:
        message: The fail-closed reason embedded in every role's finding.

    Returns:
        Three BLOCKING ``LayerResult`` in canonical role order.
    """
    return (
        _blocking_result("qa_review", message),
        _blocking_result("semantic_review", message),
        _blocking_result("doc_fidelity", message),
    )


def _blocking_result(layer_name: str, message: str) -> LayerResult:
    """Build a BLOCKING ``LayerResult`` for a failed LLM Layer-2 run."""
    return LayerResult(
        layer=layer_name,
        passed=False,
        findings=(
            Finding(
                layer=layer_name,
                check="layer2_llm.failure",
                severity=Severity.BLOCKING,
                message=message,
                trust_class=TrustClass.SYSTEM,
            ),
        ),
        metadata={"layer2_llm_error": message},
    )


def _to_layer_result(
    role: ReviewerRole, result: StructuredEvaluatorResult
) -> LayerResult:
    """Map a :class:`StructuredEvaluatorResult` to a :class:`LayerResult`.

    FK-34 §34.2.5: a single ``FAIL`` blocks the role (``passed=False``);
    ``PASS`` / ``PASS_WITH_CONCERNS`` do not block.

    Args:
        role: The reviewer role (used as the layer name).
        result: The validated per-role evaluation result.

    Returns:
        A :class:`LayerResult` carrying the evaluator's findings and audit
        metadata.
    """
    passed = result.verdict is not LlmVerdict.FAIL
    metadata: dict[str, object] = {
        "verdict": result.verdict.value,
        "raw_response_hash": result.raw_response_hash,
        "template_sha256": result.template_sha256,
    }
    if result.finding_resolutions:
        # E5: serialise the LLM verdicts under the canonical metadata key,
        # keyed by "layer:check" so run_qa_subflow decodes them back into the
        # ONE finding-resolution SSOT (resolution_map_from_metadata).
        metadata[LLM_RESOLUTION_METADATA_KEY] = serialize_resolution_map(
            result.finding_resolutions
        )
    return LayerResult(
        layer=role.value,
        passed=passed,
        findings=result.findings,
        metadata=metadata,
    )


__all__ = [
    "blocking_layer2_results",
    "run_layer2_llm",
    "run_layer2_llm_failclosed",
]
