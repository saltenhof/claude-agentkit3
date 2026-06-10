"""Layer-2 integration assertions for FK-37 context packing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput
from agentkit.verify_system.llm_evaluator.layer2_integration import run_layer2_llm
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    LlmVerdict,
    ReviewerRole,
    StructuredEvaluatorResult,
)
from agentkit.verify_system.protocols import LayerResult

if TYPE_CHECKING:
    from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
    from agentkit.verify_system.protocols import Finding


@dataclass
class _RecordingRunner:
    seen_bundle: ReviewBundle | None = None

    def run_roles(
        self,
        roles: tuple[ReviewerRole, ...],
        bundle: ReviewBundle,
        previous_findings: list[Finding] | None,
        qa_cycle_round: int,
        *,
        run_id: str | None = None,
        run_attempt: int = 1,
    ) -> dict[ReviewerRole, StructuredEvaluatorResult]:
        del previous_findings, qa_cycle_round, run_id, run_attempt
        self.seen_bundle = bundle
        return {
            role: StructuredEvaluatorResult(
                role=role,
                verdict=LlmVerdict.PASS,
                findings=(),
                finding_resolutions={},
                raw_response_hash="a" * 64,
                template_sha256="b" * 64,
            )
            for role in roles
        }


def test_run_layer2_builds_enriched_bundle_before_runner_call() -> None:
    runner = _RecordingRunner()
    doc_result = LayerResult(layer="doc_fidelity", passed=True)

    run_layer2_llm(
        runner,  # type: ignore[arg-type]
        Layer2ReviewInput(
            story_spec="story",
            diff_summary="diff",
            concept_excerpt="concept",
            handover="handover",
        ),
        story_id="AG3-067",
        qa_cycle_round=1,
        previous_findings=(),
        doc_fidelity_result=doc_result,
        arch_references="arch",
        evidence_manifest={"manifest_hash": "abc"},
    )

    assert runner.seen_bundle is not None
    assert runner.seen_bundle.arch_references == "arch"
    assert runner.seen_bundle.evidence_manifest == {"manifest_hash": "abc"}
    assert runner.seen_bundle.concept_excerpt == "concept"
