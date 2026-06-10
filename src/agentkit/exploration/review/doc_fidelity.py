"""Stage 1 of the exploration exit-gate: document fidelity (FK-23 §23.5.1).

Stage 1 is the binary, independent document-fidelity check (FK-23 §23.5.1 /
FK-32 §32.6): a *second*, independent LLM pass over the worker change-frame so
the worker cannot pass itself (FK-32 §32.6.3). It reuses the Layer-2
:class:`~agentkit.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`
with :attr:`~agentkit.verify_system.llm_evaluator.structured_evaluator.ReviewerRole.DOC_FIDELITY`
(the single ``impl_fidelity`` check, FK-34 §34.2.4) -- no second evaluator
implementation (FIX THE MODEL).

The result is strictly binary ``pass`` / ``fail`` (FK-23 §23.5.1):

* the evaluator verdict ``PASS`` -> ``pass``;
* any other verdict (``FAIL`` / ``PASS_WITH_CONCERNS``) -> ``fail`` -- a Stage 1
  FAIL is a hard architecture-conflict and rolls the gate to REJECTED (FK-23
  §23.5 (a) / FK-32 §32.6.4). No "concern" softening: Stage 1 is fail-closed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict

from agentkit.artifacts.reference import ArtifactReference
from agentkit.exploration.review.bundle import build_change_frame_bundle
from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system.conformance_service import (
    ConformanceService,
    ConformanceVerdict,
    FidelityContext,
    FidelityLevel,
    StructuredEvaluatorConformanceAdapter,
)
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    ReviewerRole,
    StructuredEvaluatorResult,
)
from agentkit.verify_system.protocols import Finding

if TYPE_CHECKING:
    from agentkit.exploration.change_frame import ChangeFrame
    from agentkit.exploration.review.persistence import ReviewResultSink
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluator,
    )


class DocFidelityResult(BaseModel):
    """Result of Stage 1 document fidelity (FK-23 §23.5.1, binary).

    Attributes:
        status: Binary outcome -- ``"pass"`` only when the evaluator verdict is
            ``PASS``; ``"fail"`` otherwise (fail-closed, no concern softening).
        findings: The evaluator findings (empty on a clean PASS).
        evaluator_result_ref: Reference to the persisted evaluator-result QA
            artifact (the audit anchor; never a fabricated reference).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["pass", "fail"]
    findings: tuple[Finding, ...]
    evaluator_result_ref: ArtifactReference | None


class DocFidelityChecker:
    """Stage 1 document-fidelity checker (FK-23 §23.5.1).

    Wraps the Layer-2 :class:`StructuredEvaluator` in the ``DOC_FIDELITY`` role
    and projects its verdict onto a binary pass/fail outcome. Persists the
    evaluator result via the injected :class:`ReviewResultSink` so the returned
    reference is a real audit anchor.
    """

    def __init__(
        self,
        structured_evaluator: StructuredEvaluator,
        result_sink: ReviewResultSink,
        *,
        story_context: StoryContext | None = None,
        conformance_service: ConformanceService | None = None,
    ) -> None:
        """Initialize the checker.

        Args:
            structured_evaluator: The Layer-2 evaluator (DI; the LLM-boundary
                seam). Called with :attr:`ReviewerRole.DOC_FIDELITY`.
            result_sink: Persistence port that stores the evaluator result as a
                QA artifact and returns its typed reference (DI).
        """
        self._sink = result_sink
        self._story_context = story_context
        self._conformance = conformance_service or ConformanceService(
            StructuredEvaluatorConformanceAdapter(structured_evaluator)
        )

    def check(self, change_frame: ChangeFrame) -> DocFidelityResult:
        """Run the binary document-fidelity check on the change-frame.

        Args:
            change_frame: The validated worker change-frame (FK-23 §23.4).

        Returns:
            A :class:`DocFidelityResult` -- ``"pass"`` only on an evaluator
            ``PASS``; ``"fail"`` on any other verdict (fail-closed).

        Raises:
            StructuredEvaluatorError: On an unparseable / schema-violating LLM
                response (propagated fail-closed; never a silent PASS).
            LlmClientError: If the LLM transport fails (propagated fail-closed).
        """
        bundle = build_change_frame_bundle(change_frame, review_round=1)
        fidelity = self._conformance.check_fidelity(
            FidelityLevel.DESIGN,
            _context_from_change_frame(
                change_frame,
                bundle=bundle,
                story_context=self._story_context,
            ),
        )
        evaluator_result = cast(
            "StructuredEvaluatorResult | None", fidelity.evaluator_result
        )
        ref: ArtifactReference | None = None
        if evaluator_result is not None:
            ref = self._sink.persist(
                change_frame=change_frame,
                stage=ReviewerRole.DOC_FIDELITY.value,
                review_round=1,
                evaluator_result=evaluator_result,
            )
        status: Literal["pass", "fail"] = (
            "pass"
            if fidelity.conformance_verdict is ConformanceVerdict.PASS
            else "fail"
        )
        return DocFidelityResult(
            status=status,
            findings=fidelity.findings,
            evaluator_result_ref=ref,
        )


def _context_from_change_frame(
    change_frame: ChangeFrame,
    *,
    bundle: object,
    story_context: StoryContext | None,
) -> FidelityContext:
    """Project the exploration change-frame into a conformance context."""
    project_root = (
        story_context.project_root
        if story_context is not None and story_context.project_root is not None
        else None
    )
    if project_root is None:
        msg = "DocFidelityChecker requires story_context.project_root for manifest-index lookup"
        raise ValueError(msg)
    module = _module_from_change_frame(change_frame)
    story_type = (
        story_context.story_type.value
        if story_context is not None
        else StoryType.IMPLEMENTATION.value
    )
    subject = json.dumps(
        change_frame.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
    )
    return FidelityContext(
        story_id=change_frame.story_id,
        run_id=change_frame.run_id,
        project_root=project_root,
        story_type=story_type,
        module=module,
        subject=subject,
        story_description=change_frame.goal_and_scope.changes,
        tags=("design", "document-fidelity"),
        review_bundle=bundle,
    )


def _module_from_change_frame(change_frame: ChangeFrame) -> str:
    affected = change_frame.affected_building_blocks.affected
    if not affected:
        return "*"
    return affected[0].split("/", maxsplit=1)[0]


__all__ = ["DocFidelityChecker", "DocFidelityResult"]
