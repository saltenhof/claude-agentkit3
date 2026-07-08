"""Layer-2 conformance builds reviewer execution and maps implementation-fidelity results."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
    TrustClass,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.verify_system.conformance_service import FidelityContext
    from agentkit.backend.verify_system.contract import VerifyContextBundle
    from agentkit.backend.verify_system.evidence.bundle_manifest import BundleManifest
    from agentkit.backend.verify_system.llm_evaluator import Layer2ReviewInput, ParallelEvalRunner
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluatorResult,
    )
    from agentkit.backend.verify_system.routing import QALayerKind
    from agentkit.backend.verify_system.system import VerifySystem


def _run_layer2(
    system: VerifySystem,
    *,
    ctx: VerifyContextBundle,
    story_id: str,
    kind: QALayerKind,
    effective_review_input: object | None,
    story_ctx: object | None,
    qa_cycle_round: int,
    previous_findings: tuple[Finding, ...],
    arch_references: str = "",
    evidence_manifest: BundleManifest | dict[str, object] | str | None = None,
) -> tuple[LayerResult, LayerResult, LayerResult]:
    """Return the three Layer-2 role results (qa/semantic/doc) in canonical order.

    Module-level helper (keeps ``VerifySystem`` under the class-LOC budget).
    Resolution order (AG3-043 E6):

    1. An explicitly-wired ``system.layer2_runner`` (test double / explicit
       composition) -> three parallel LLM evaluations (FK-27 §27.5.1),
       fail-closed via ``run_layer2_llm_failclosed``.
    2. Otherwise, a wired ``system.layer2_llm_client`` (productive default,
       ``build_verify_system``) -> build a PER-RUN runner with the run's
       ``StoryContext`` + ``PromptRuntimeMaterializer`` (FK-44 §44.4.2) and run
       the three evaluations. "Reviews ALWAYS take place" (FK-27 §27.5): when
       the run's ``StoryContext`` is unresolvable the reviews still RUN and
       FAIL-CLOSED (three BLOCKING results), never a silent stub fallback.
    3. Only when NEITHER is wired -> the historical deterministic Layer-2
       reviewers via ``system._execute_layer``.

    Args:
        system: The owning ``VerifySystem`` (provides the layer instances and
            the per-layer executor).
        ctx: Run-time context bundle.
        story_id: Story display-ID.
        kind: ``QALayerKind.LLM_EVALUATOR``.
        effective_review_input: Normalised ``Layer2ReviewInput``.
        story_ctx: Pre-resolved ``StoryContext`` (or ``None``).
        qa_cycle_round: 1-based QA-cycle round.
        previous_findings: Prior-round findings (remediation context).

    Returns:
        Three ``LayerResult`` aligned with ``_LAYER_2_SPECS``.
    """
    runner = _resolve_layer2_runner(system, story_ctx, ctx.story_dir)
    if runner is None and system.layer2_llm_client is None:
        # No LLM wired at all -> historical deterministic reviewers.
        results = [
            system._execute_layer(  # noqa: SLF001  -- same-module helper
                layer_instance, ctx, story_id, kind,
                review_input=effective_review_input,
                story_context=story_ctx,
            )
            for layer_instance, _spec in system._layer2_pairs()  # noqa: SLF001
        ]
        return (results[0], results[1], results[2])

    from agentkit.backend.verify_system.llm_evaluator.layer2_integration import (
        blocking_layer2_results,
        run_layer2_llm_failclosed,
    )

    if runner is None:
        # An LLM client is wired but no per-run runner could be built (the run's
        # StoryContext is unresolvable). Reviews must still run -> fail-closed
        # BLOCKING, NOT a silent deterministic stub fallback (FK-27 §27.5).
        return blocking_layer2_results(
            "Layer 2 LLM client is wired but the run StoryContext is "
            "unresolvable; reviews fail-closed (FK-27 §27.5)."
        )

    review_input = _normalise_layer2_input(effective_review_input)
    conformance_context = _build_impl_conformance_context(
        review_input,
        story_id=story_id,
        run_id=ctx.run_id,
        story_ctx=story_ctx,
        story_dir=ctx.story_dir,
        previous_findings=previous_findings,
        qa_cycle_round=qa_cycle_round,
        arch_references=arch_references,
        evidence_manifest=evidence_manifest,
        bundle_token_limit=system.layer2_bundle_token_limit,
    )
    doc_fidelity_result = _run_impl_conformance(
        system,
        runner=runner,
        conformance_context=conformance_context,
    )
    # ERROR 3 fix: propagate ctx.run_id / ctx.attempt so prompt-audit envelopes
    # are keyed to the current run (FK-11 §11.4.6a).  Without these, the
    # StructuredEvaluator silently skips persistence even when artifact_manager
    # is injected (persist_prompt_audit guards on run_id presence).
    return run_layer2_llm_failclosed(
        runner,
        review_input,
        story_id=story_id,
        qa_cycle_round=qa_cycle_round,
        previous_findings=previous_findings,
        doc_fidelity_result=doc_fidelity_result,
        run_id=ctx.run_id,
        run_attempt=ctx.attempt,
        arch_references=arch_references,
        evidence_manifest=evidence_manifest,
        bundle_token_limit=system.layer2_bundle_token_limit,
    )


def _normalise_layer2_input(effective_review_input: object | None) -> Layer2ReviewInput:
    """Return a concrete ``Layer2ReviewInput`` (empty default when not one)."""
    from agentkit.backend.verify_system.llm_evaluator.inputs import Layer2ReviewInput as _L2Input

    return (
        effective_review_input
        if isinstance(effective_review_input, _L2Input)
        else _L2Input()
    )


def _build_impl_conformance_context(
    review_input: Layer2ReviewInput,
    *,
    story_id: str,
    run_id: str,
    story_ctx: object | None,
    story_dir: Path,
    previous_findings: tuple[Finding, ...],
    qa_cycle_round: int,
    arch_references: str,
    evidence_manifest: BundleManifest | dict[str, object] | str | None,
    bundle_token_limit: int,
) -> FidelityContext | None:
    """Build the implementation-fidelity context when StoryContext is available."""
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.types import StoryType
    from agentkit.backend.verify_system.conformance_service import FidelityContext
    from agentkit.backend.verify_system.llm_evaluator.bundle import build_review_bundle

    if not isinstance(story_ctx, StoryContext):
        return None
    review_bundle = build_review_bundle(
        review_input,
        story_id=story_id,
        qa_cycle_round=qa_cycle_round,
        previous_findings=list(previous_findings) if previous_findings else None,
        arch_references=arch_references,
        evidence_manifest=evidence_manifest,
        bundle_token_limit=bundle_token_limit,
    )
    subject = "\n\n".join(
        (
            review_input.story_spec,
            review_input.diff_summary,
            review_input.concept_excerpt,
            review_input.handover,
        )
    )
    project_root = story_ctx.project_root or story_dir
    module = story_ctx.participating_repos[0] if story_ctx.participating_repos else "*"
    story_type = (
        story_ctx.story_type.value
        if story_ctx.story_type is not None
        else StoryType.IMPLEMENTATION.value
    )
    return FidelityContext(
        story_id=story_id,
        run_id=run_id,
        project_root=project_root,
        story_type=story_type,
        module=module,
        subject=subject,
        story_description=story_ctx.title,
        tags=("impl", "document-fidelity"),
        review_bundle=review_bundle,
        previous_findings=previous_findings,
        qa_cycle_round=qa_cycle_round,
    )


def _run_impl_conformance(
    system: VerifySystem,
    *,
    runner: ParallelEvalRunner,
    conformance_context: FidelityContext | None,
) -> LayerResult | None:
    """Run implementation fidelity through ConformanceService when context exists."""
    if conformance_context is None:
        return None
    from agentkit.backend.verify_system.conformance_service import (
        ConformanceService,
        FidelityLevel,
        StructuredEvaluatorConformanceAdapter,
    )
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        ReviewerRole,
        StructuredEvaluatorResult,
    )

    conformance_kwargs: dict[str, int] = {}
    if system.conformance_config is not None:
        conformance_kwargs["file_upload_threshold"] = (
            system.conformance_config.file_upload_threshold
        )
        conformance_kwargs["hard_limit"] = system.conformance_config.hard_limit
    service = ConformanceService(
        StructuredEvaluatorConformanceAdapter(runner),
        emitter=system.conformance_emitter,
        **conformance_kwargs,
    )
    fidelity = service.check_fidelity(FidelityLevel.IMPL, conformance_context)
    if isinstance(fidelity.evaluator_result, StructuredEvaluatorResult):
        return _layer_result_from_structured_doc_fidelity(fidelity.evaluator_result)
    return LayerResult(
        layer=ReviewerRole.DOC_FIDELITY.value,
        passed=False,
        findings=fidelity.findings
        or (
            Finding(
                layer=ReviewerRole.DOC_FIDELITY.value,
                check="impl_fidelity",
                severity=Severity.BLOCKING,
                message=fidelity.reason,
                trust_class=TrustClass.SYSTEM,
            ),
        ),
        metadata={"verdict": "FAIL", "reason": fidelity.reason},
    )


def _layer_result_from_structured_doc_fidelity(
    result: StructuredEvaluatorResult,
) -> LayerResult:
    """Map the structured doc-fidelity result without importing layer2 glue."""
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import LlmVerdict
    from agentkit.backend.verify_system.remediation.finding_resolution import (
        LLM_RESOLUTION_METADATA_KEY,
        serialize_resolution_map,
    )

    verdict = result.verdict
    findings = result.findings
    raw_hash = result.raw_response_hash
    template_hash = result.template_sha256
    finding_resolutions = result.finding_resolutions
    metadata: dict[str, object] = {
        "verdict": verdict.value,
        "raw_response_hash": raw_hash,
        "template_sha256": template_hash,
    }
    if finding_resolutions:
        metadata[LLM_RESOLUTION_METADATA_KEY] = serialize_resolution_map(
            finding_resolutions
        )
    return LayerResult(
        layer="doc_fidelity",
        passed=verdict is not LlmVerdict.FAIL,
        findings=findings,
        metadata=metadata,
    )


def _resolve_layer2_runner(
    system: VerifySystem,
    story_ctx: object | None,
    story_dir: Path,
) -> ParallelEvalRunner | None:
    """Resolve the Layer-2 runner for this run (AG3-043 E6).

    Returns the explicitly-wired ``system.layer2_runner`` when present;
    otherwise, when a ``system.layer2_llm_client`` is wired, builds a PER-RUN
    ``ParallelEvalRunner`` bound to the run's ``StoryContext`` via a
    ``PromptRuntimeMaterializer`` (FK-44 §44.4.2). Returns ``None`` when no
    runner can be built (no client, or no resolvable ``StoryContext``); the
    caller decides between the deterministic path and the fail-closed path.

    Args:
        system: The owning ``VerifySystem``.
        story_ctx: Pre-resolved ``StoryContext`` (or ``None``).
        story_dir: The run's story working directory.

    Returns:
        A ``ParallelEvalRunner`` or ``None``.
    """
    if system.layer2_runner is not None:
        return system.layer2_runner
    if system.layer2_llm_client is None:
        return None
    from agentkit.backend.story_context_manager.models import StoryContext

    if not isinstance(story_ctx, StoryContext):
        return None
    from agentkit.backend.verify_system.llm_evaluator.parallel_runner import ParallelEvalRunner
    from agentkit.backend.verify_system.llm_evaluator.prompt_materializer import (
        PromptRuntimeMaterializer,
    )
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluator,
    )

    materializer = PromptRuntimeMaterializer(
        ctx=story_ctx,
        story_dir=story_dir,
        artifact_manager=system.artifact_manager,
        story_context_port=system.story_context_port,
    )
    # ERROR 3 fix: inject system.artifact_manager so prompt-audit envelopes are
    # persisted via the real ArtifactManager (FK-11 §11.4.6a). Without this the
    # StructuredEvaluator silently skips persistence on every production run.
    evaluator = StructuredEvaluator(
        system.layer2_llm_client,
        materializer,
        artifact_manager=system.artifact_manager,
    )
    return ParallelEvalRunner(evaluator)
