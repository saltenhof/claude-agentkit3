"""Routed QA layer execution runs selected verification layers and records their layer artifacts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.verify_system import _artifact_specs
from agentkit.backend.verify_system.layer2_conformance import _run_layer2
from agentkit.backend.verify_system.review_completion import (
    ReviewCompletionEvent,
)
from agentkit.backend.verify_system.routing import QALayerKind

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agentkit.backend.verify_system.contract import VerifyContextBundle
    from agentkit.backend.verify_system.evidence.bundle_manifest import BundleManifest
    from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.backend.verify_system.protocols import Finding, LayerResult
    from agentkit.backend.verify_system.qa_cycle.lifecycle import QaCycleState
    from agentkit.backend.verify_system.system import VerifySystem



@dataclass(frozen=True)
class _DataLayerInputs:
    """Read-only per-run inputs shared by the non-gate data layers.

    S107 param object (behaviour-preserving): groups the cohesive Layer-2/3
    review inputs that always travel together from ``_run_qa_subflow`` into
    :func:`_run_data_layer_kind` / :func:`_run_layer2`. Bundling them keeps the
    executor's parameter count within the authorised budget without changing any
    value passed.

    Attributes:
        effective_review_input: Normalised Layer-2 review input.
        story_ctx: Pre-resolved ``StoryContext`` (or ``None``).
        qa_cycle_round: 1-based QA-cycle round (``> 1`` => remediation; passed
            to the LLM runner for finding-resolution).
        previous_findings: Prior-round findings carried into the LLM runner's
            remediation bundle (DK-04 §4.6).
        arch_references: Architecture references resolved by the context
            sufficiency pre-step (Layer-2 enrichment).
        evidence_manifest: Bundle manifest / evidence reference for Layer-2.
    """

    effective_review_input: object | None
    story_ctx: object | None
    qa_cycle_round: int
    previous_findings: tuple[Finding, ...]
    arch_references: str = ""
    evidence_manifest: BundleManifest | dict[str, object] | str | None = None


def _run_data_layer_kind(
    system: VerifySystem,
    *,
    kind: QALayerKind,
    ctx: VerifyContextBundle,
    story_id: str,
    now_str: str,
    qa_cycle_fields: dict[str, object],
    layer_results: list[LayerResult],
    artifact_refs_written: list[str],
    inputs: _DataLayerInputs,
) -> None:
    """Execute a non-gate data layer and write its envelope(s).

    Extracted from :meth:`run_qa_subflow` (S3776) without behaviour change.

    * ``LLM_EVALUATOR`` (AG3-043): when an ``layer2_runner`` is wired, runs
      the three parallel LLM evaluations (FK-27 §27.5.1); otherwise falls
      back to the three deterministic Layer-2 reviewers. Either way it
      produces three ``LayerResult`` (one per role) and three envelopes.
    * STRUCTURAL / ADVERSARIAL: resolves the single layer instance, executes
      it once and writes its single artefact spec(s).

    Args:
        kind: The (non-POLICY, non-SONARQUBE_GATE) layer kind to run.
        ctx: Run-time context bundle.
        story_id: Story display-ID.
        now_str: Pre-computed ISO timestamp for envelope writes.
        qa_cycle_fields: QA-cycle identity fields embedded in payloads.
        layer_results: Mutable accumulator of layer results (appended in
            place).
        artifact_refs_written: Mutable accumulator of artefact filenames
            (appended in place).
        inputs: Cohesive read-only Layer-2/3 review inputs (S107 param object).
    """
    self = system
    if kind is QALayerKind.LLM_EVALUATOR:
        results = _run_layer2(
            self,
            ctx=ctx,
            story_id=story_id,
            kind=kind,
            effective_review_input=inputs.effective_review_input,
            story_ctx=inputs.story_ctx,
            qa_cycle_round=inputs.qa_cycle_round,
            previous_findings=inputs.previous_findings,
            arch_references=inputs.arch_references,
            evidence_manifest=inputs.evidence_manifest,
        )
        pairs = list(zip(results, _artifact_specs.LAYER_2_SPECS, strict=True))
    else:
        layer_instance = self._layer_for_kind(kind)
        result = self._execute_layer(
            layer_instance, ctx, story_id, kind,
            review_input=inputs.effective_review_input,
            story_context=inputs.story_ctx,
        )
        pairs = [(result, spec) for spec in _kind_to_single_artifacts(kind)]

    for result, spec in pairs:
        layer_results.append(result)
        # FK-48 §48.1.7 (AG3-079): when a layer materialised its own canonical QA
        # artefact (the Layer-3 runtime writes the rich ``adversarial.json`` schema
        # 3.1 via the ArtifactManager), the subflow MUST NOT overwrite it with the
        # generic LayerResult projection — that would discard the sparring proof /
        # mandatory_target_results (single source of truth, FIX THE MODEL).
        if result.metadata.get("artifact_materialized") is True:
            artifact_refs_written.append(spec.filename)
            continue
        self._write_layer_envelope(
            spec=spec,
            result=result,
            ctx=ctx,
            story_id=story_id,
            now_str=now_str,
            qa_cycle_fields=qa_cycle_fields,
        )
        artifact_refs_written.append(spec.filename)
        # FIX-C (FK-27 §27.4.3 / §27.5.5): emit ``llm_call_complete`` ONLY
        # after the Layer-2 review artefact write above SUCCEEDED -- never on
        # a bare API response. The role is ``result.layer`` (qa_review /
        # semantic_review / doc_fidelity), which is exactly the per-role
        # filter the ``guard.multi_llm`` Gate 2 counts (FK-37 §37.1.6). Only
        # Layer-2 reviews carry a mandatory reviewer role; structural /
        # adversarial layers do not emit completion events.
        if kind is QALayerKind.LLM_EVALUATOR:
            self.review_completion_sink.review_completed(
                ReviewCompletionEvent(
                    story_id=story_id,
                    role=result.layer,
                    artifact_filename=spec.filename,
                )
            )


@dataclass(frozen=True)
class _LayerLoopResult:
    """Outcome of the data-layer execution loop (S3776 extraction).

    Attributes:
        sonar_fail_decision: The direct fail-closed ``VerifyDecision`` when an
            APPLICABLE SonarQube gate failed (short-circuit, FK-33 §33.6.3);
            ``None`` otherwise.
        context_sufficiency_artifact: The serialised context-sufficiency
            artefact produced by the Layer-2 pre-step, or ``None`` when Layer 2
            was not routed.
    """

    sonar_fail_decision: VerifyDecision | None
    context_sufficiency_artifact: dict[str, object] | None


def _execute_data_layers(
    system: VerifySystem,
    *,
    layer_kinds: tuple[QALayerKind, ...],
    ctx: VerifyContextBundle,
    story_id: str,
    now_str: str,
    qa_cycle_fields: dict[str, object],
    cycle_state: QaCycleState,
    story_ctx: object | None,
    effective_review_input: object | None,
    previous_findings: tuple[Finding, ...],
    layer_results: list[LayerResult],
    artifact_refs_written: list[str],
) -> _LayerLoopResult:
    """Execute the selected data layers in order (extracted from ``_run_qa_subflow``).

    Behaviour-preserving S3776 extraction: the break/continue/gate semantics are
    IDENTICAL to the prior inline ``for kind in layer_kinds`` loop. POLICY is
    skipped (handled post-loop); an APPLICABLE SonarQube-gate FAIL short-circuits
    (break) and is surfaced as ``sonar_fail_decision``; LLM_EVALUATOR runs the
    context-sufficiency pre-step (enriching the review input) before the data
    layer. ``layer_results`` and ``artifact_refs_written`` are appended in place.

    Args:
        system: The owning ``VerifySystem``.
        layer_kinds: The ordered selected layer kinds.
        ctx: Run-time context bundle.
        story_id: Story display-ID.
        now_str: Pre-computed ISO timestamp for envelope writes.
        qa_cycle_fields: QA-cycle identity fields embedded in payloads.
        cycle_state: Resolved QA-cycle state (round carried into the layers).
        story_ctx: Pre-resolved ``StoryContext`` (or ``None``).
        effective_review_input: Normalised Layer-2 review input (the pre-step
            may enrich it before the LLM evaluation).
        previous_findings: Prior-round findings (remediation context).
        layer_results: Mutable accumulator of layer results.
        artifact_refs_written: Mutable accumulator of artefact filenames.

    Returns:
        A :class:`_LayerLoopResult` carrying the gate short-circuit decision (or
        ``None``) and the context-sufficiency artefact (or ``None``).
    """
    self = system
    context_sufficiency_artifact: dict[str, object] | None = None
    layer2_arch_references = ""
    layer2_evidence_manifest: BundleManifest | dict[str, object] | str | None = None

    for kind in layer_kinds:
        if kind is QALayerKind.POLICY:
            # Policy runs after all data layers; handled in step 5/6.
            continue

        if kind is QALayerKind.SONARQUBE_GATE:
            sonar_fail_decision = self._run_sonarqube_gate_kind(
                ctx=ctx,
                story_id=story_id,
                now_str=now_str,
                qa_cycle_fields=qa_cycle_fields,
                layer_results=layer_results,
                artifact_refs_written=artifact_refs_written,
            )
            if sonar_fail_decision is not None:
                # FK-33 §33.6.3: an APPLICABLE gate fail-closed routes
                # DIRECTLY to failed WITHOUT policy aggregation. It does NOT
                # bypass the remediation loop (FK-27 §27.6a.2): the FAIL is
                # fed through the SAME escalation path below (break, do not
                # return). No decision.json on this path (the gate envelope
                # is the verdict carrier).
                return _LayerLoopResult(
                    sonar_fail_decision=sonar_fail_decision,
                    context_sufficiency_artifact=context_sufficiency_artifact,
                )
            continue

        if kind is QALayerKind.LLM_EVALUATOR:
            sufficiency = self._run_context_sufficiency_pre_step(
                ctx=ctx,
                story_id=story_id,
                now_str=now_str,
                qa_cycle_fields=qa_cycle_fields,
                review_input=effective_review_input,
                story_ctx=story_ctx,
            )
            effective_review_input = sufficiency.enriched_input
            layer2_arch_references = sufficiency.arch_references
            layer2_evidence_manifest = sufficiency.evidence_manifest
            context_sufficiency_artifact = sufficiency.artifact.model_dump(
                mode="json"
            )
            artifact_refs_written.append(
                _artifact_specs.CONTEXT_SUFFICIENCY_ARTIFACT_SPEC.filename
            )

        self._run_data_layer_kind(
            kind=kind,
            ctx=ctx,
            story_id=story_id,
            now_str=now_str,
            qa_cycle_fields=qa_cycle_fields,
            layer_results=layer_results,
            artifact_refs_written=artifact_refs_written,
            inputs=_DataLayerInputs(
                effective_review_input=effective_review_input,
                story_ctx=story_ctx,
                qa_cycle_round=cycle_state.round,
                previous_findings=previous_findings,
                arch_references=layer2_arch_references,
                evidence_manifest=layer2_evidence_manifest,
            ),
        )

    return _LayerLoopResult(
        sonar_fail_decision=None,
        context_sufficiency_artifact=context_sufficiency_artifact,
    )


def _kind_to_single_artifacts(
    kind: QALayerKind,
) -> tuple[_artifact_specs._LayerArtifactSpec, ...]:
    """Return the single-artefact specs for Layer 1 or Layer 3 (module helper).

    Layer 2 is handled separately via ``VerifySystem._layer2_pairs``. Kept at
    module level (not a method) to hold ``VerifySystem`` under the class-LOC
    budget.

    Args:
        kind: Layer kind (STRUCTURAL or ADVERSARIAL).

    Returns:
        Tuple with one ``_LayerArtifactSpec``.
    """
    if kind is QALayerKind.STRUCTURAL:
        return _artifact_specs.LAYER_1_ARTIFACTS
    if kind is QALayerKind.ADVERSARIAL:
        return _artifact_specs.LAYER_3_ARTIFACTS
    msg = f"_kind_to_single_artifacts called with non-single kind {kind!r}"
    raise ValueError(msg)  # pragma: no cover
