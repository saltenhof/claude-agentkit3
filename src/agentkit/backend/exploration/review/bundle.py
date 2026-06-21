"""Build a Layer-2 :class:`ReviewBundle` from a change-frame (FK-23 §23.5).

The three exploration-review stages (doc-fidelity, design-review,
design-challenge) all evaluate the SAME subject -- the worker-produced
change-frame (FK-23 §23.4) -- through the Layer-2
:class:`~agentkit.backend.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`.
That evaluator consumes a
:class:`~agentkit.backend.verify_system.llm_evaluator.bundle.ReviewBundle`, so this
module is the single, deterministic projection of a :class:`ChangeFrame` onto a
bundle. It reuses the existing ``build_review_bundle`` packing (size bounds,
truncation protocol) instead of introducing a second bundle builder
(FIX THE MODEL: no second truth).

The change-frame is serialized into the bundle's ``handover`` slot (it is the
worker's design output, FK-23 §23.4) and a deterministic ``diff_summary`` lists
the affected building blocks; the ``concept_refs`` carry the conformance
statement's reference documents (FK-23 §23.4.1) so the reviewers see the very
anchors the worker claimed conformance against.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.llm_evaluator.bundle import build_review_bundle
from agentkit.backend.verify_system.llm_evaluator.inputs import Layer2ReviewInput

if TYPE_CHECKING:
    from agentkit.backend.exploration.change_frame import ChangeFrame
    from agentkit.backend.verify_system.llm_evaluator.bundle import ReviewBundle
    from agentkit.backend.verify_system.protocols import Finding


def build_change_frame_bundle(
    change_frame: ChangeFrame,
    *,
    review_round: int,
    previous_findings: list[Finding] | None = None,
) -> ReviewBundle:
    """Project a change-frame onto a size-bounded :class:`ReviewBundle`.

    Args:
        change_frame: The validated worker change-frame (FK-23 §23.4) under
            review.
        review_round: 1-based review round (``> 1`` => remediation mode; carries
            the previous round's findings to the evaluator, FK-34 §34.9).
        previous_findings: Prior-round findings for the remediation prompt
            section (FK-34 §34.9). ``None`` / empty in the initial round.

    Returns:
        A frozen, size-bounded :class:`ReviewBundle` whose ``handover`` is the
        serialized change-frame and whose ``concept_refs`` are the conformance
        statement's reference documents.
    """
    frame_json = json.dumps(
        change_frame.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
    )
    affected = change_frame.affected_building_blocks.affected
    diff_summary = "affected building blocks: " + ", ".join(affected)
    review_input = Layer2ReviewInput(
        story_spec=change_frame.goal_and_scope.changes,
        diff_summary=diff_summary,
        concept_excerpt="",
        handover=frame_json,
    )
    return build_review_bundle(
        review_input,
        story_id=change_frame.story_id,
        qa_cycle_round=review_round,
        concept_refs=list(change_frame.conformance_statement.reference_documents),
        previous_findings=previous_findings,
    )


__all__ = ["build_change_frame_bundle"]
