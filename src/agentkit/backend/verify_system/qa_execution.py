"""QA-subflow execution helpers for the verify-system top surface."""


from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.core_types import ArtifactClass, PolicyVerdict, QaContext
from agentkit.backend.verify_system import _artifact_specs
from agentkit.backend.verify_system.contract import (
    QaSubflowOutcome,
    VerifyContextBundle,
    _QaSubflowExecutionResult,
)
from agentkit.backend.verify_system.implementation_evidence_gate import (
    evaluate_implementation_evidence_gate,
)
from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
from agentkit.backend.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
    TrustClass,
)
from agentkit.backend.verify_system.qa_cycle import integration as _qa
from agentkit.backend.verify_system.review_completion import (
    ReviewCompletionEvent,
)
from agentkit.backend.verify_system.routing import QALayerKind, select_layers
from agentkit.backend.verify_system.stage_registry.registry import StageRegistry
from agentkit.backend.verify_system.stage_registry.stages import StageKind

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.artifacts import ArtifactReference
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.types import (
        ImplementationContract,
        StoryType,
    )
    from agentkit.backend.verify_system.conformance_service import FidelityContext
    from agentkit.backend.verify_system.evidence.bundle_manifest import BundleManifest
    from agentkit.backend.verify_system.llm_evaluator import Layer2ReviewInput, ParallelEvalRunner
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluatorResult,
    )
    from agentkit.backend.verify_system.qa_cycle.lifecycle import QaCycleState
    from agentkit.backend.verify_system.system import VerifySystem


def _run_fast_floor(
    system: VerifySystem,
    *,
    ctx: VerifyContextBundle,
    story_id: str,
    story_ctx: StoryContext | None,
) -> QaSubflowOutcome:
    """Run the fast-mode QA floor: Layer 1 (structural) + tests-green.

    FK-24 §24.3.4 Mode-Profil: in ``mode == fast`` the QA-subflow degenerates
    to Layer 1 (deterministic structural checks) AND the hard, non-disableable
    tests-green floor. Layers 2-4, the Sonar gate and the feedback/remediation
    loop are SKIPPED (``OUT``). The floor PASSes only when BOTH the structural
    layer passes AND the injected ``fast_test_runner`` confirms tests green.

    FAIL-CLOSED (NO ERROR BYPASSING): a red test -> FAIL; an unconfirmable
    result (no ``fast_test_runner`` wired) -> FAIL. The cycle is still
    resolved (idle -> ``start_cycle``) so the four identity fields are
    surfaced for the state owner; there is no remediation/escalation loop on
    the fast path (the human accompanies the story).

    Args:
        ctx: Run-time context bundle.
        story_id: Story display-ID.
        story_ctx: The pre-resolved fast-mode ``StoryContext``.

    Returns:
        A ``QaSubflowOutcome`` carrying the floor verdict (PASS/FAIL).
    """
    self = system
    now_str = _qa.utc_now_iso()
    cycle_state = self.qa_cycle_lifecycle.start_cycle(ctx.story_dir)
    qa_cycle_fields = _qa.qa_cycle_state_to_fields(cycle_state)

    structural = self._execute_layer(
        self.layer_1, ctx, story_id, QALayerKind.STRUCTURAL, story_context=story_ctx
    )
    tests_finding = self._fast_tests_green_finding(ctx.story_dir)
    floor_findings = (
        (*structural.findings, tests_finding)
        if tests_finding is not None
        else structural.findings
    )
    floor_passed = structural.passed and tests_finding is None
    floor_result = LayerResult(
        layer=self.layer_1.name,
        passed=floor_passed,
        findings=floor_findings,
        metadata={
            **structural.metadata,
            "fast_mode": True,
            "tests_green": tests_finding is None,
        },
    )

    self._write_layer_envelope(
            spec=_artifact_specs.LAYER_1_ARTIFACTS[0],
        result=floor_result,
        ctx=ctx,
        story_id=story_id,
        now_str=now_str,
        qa_cycle_fields=qa_cycle_fields,
    )

    verdict = PolicyVerdict.PASS if floor_passed else PolicyVerdict.FAIL
    summary = (
        "fast-mode QA floor PASS (structural + tests green)"
        if floor_passed
        else "fast-mode QA floor FAIL (structural or tests-green floor not met)"
    )
    decision = VerifyDecision(
        passed=floor_passed,
        verdict=verdict,
        layer_results=(floor_result,),
        all_findings=floor_findings,
        blocking_findings=tuple(
            f for f in floor_findings if f.severity == Severity.BLOCKING
        ),
        summary=summary,
    )
    logger.info(
        "run_qa_subflow fast-mode floor: story=%s verdict=%s tests_green=%s",
        story_id,
        verdict,
        tests_finding is None,
    )
    return QaSubflowOutcome(
        verdict=verdict,
        decision=decision,
            artifact_refs=(_artifact_specs.LAYER_1_ARTIFACTS[0].filename,),
        attempt_nr=ctx.attempt,
        qa_cycle_round=cycle_state.round,
        feedback=None,
        qa_cycle_id=cycle_state.qa_cycle_id,
        evidence_epoch=cycle_state.evidence_epoch,
        evidence_fingerprint=cycle_state.evidence_fingerprint,
        escalated=False,
        closure_blocked=False,
    )


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


def _evaluate_implementation_terminality_precondition(
    system: VerifySystem,
    *,
    ctx: VerifyContextBundle,
    story_id: str,
    story_ctx: StoryContext | None,
    qa_context: QaContext,
) -> QaSubflowOutcome | None:
    """Run the FK-24 implementation-evidence gate before implementation QA."""
    if qa_context not in (
        QaContext.IMPLEMENTATION_INITIAL,
        QaContext.IMPLEMENTATION_REMEDIATION,
    ):
        return None
    if story_ctx is None:
        return _implementation_terminality_blocked_outcome(
            ctx=ctx,
            story_id=story_id,
            reason=(
                "Implementation-Evidence-Gate: StoryContext is missing for "
                "implementation QA; cannot prove FK-24 implementation "
                "terminality -> fail-closed "
                "(IMPLEMENTATION_REQUIRED_AFTER_EXPLORATION)."
            ),
        )
    story_type = story_ctx.story_type
    evidence = system.implementation_change_evidence_port.collect(ctx.story_dir)
    gate = evaluate_implementation_evidence_gate(
        story_type=story_type,
        story_dir=ctx.story_dir,
        change_evidence=evidence,
    )
    if gate.passed:
        return None
    reason = (
        gate.blocking_reason
        or "Implementation-Evidence-Gate: implementation evidence is missing."
    )
    return _implementation_terminality_blocked_outcome(
        ctx=ctx,
        story_id=story_id,
        reason=reason,
    )


def _implementation_terminality_blocked_outcome(
    *,
    ctx: VerifyContextBundle,
    story_id: str,
    reason: str,
) -> QaSubflowOutcome:
    """Build the fail-closed AG3-058 terminality outcome."""
    finding = Finding(
        layer="structural",
        check="implementation_evidence.required_after_exploration",
        severity=Severity.BLOCKING,
        message=reason,
        trust_class=TrustClass.SYSTEM,
        file_path=str(ctx.story_dir),
    )
    layer_result = LayerResult(
        layer="structural",
        passed=False,
        findings=(finding,),
        metadata={"terminality_precondition": "implementation_evidence"},
    )
    decision = VerifyDecision(
        passed=False,
        verdict=PolicyVerdict.FAIL,
        layer_results=(layer_result,),
        all_findings=(finding,),
        blocking_findings=(finding,),
        summary=reason,
    )
    logger.warning(
        "implementation evidence precondition failed: story=%s reason=%s",
        story_id,
        reason,
    )
    return QaSubflowOutcome(
        verdict=PolicyVerdict.FAIL,
        decision=decision,
        artifact_refs=(),
        attempt_nr=ctx.attempt,
        qa_cycle_round=0,
        escalated=True,
    )


def _run_qa_subflow(
    system: VerifySystem,
    ctx: VerifyContextBundle,
    story_id: str,
    qa_context: QaContext,
    target: ArtifactReference,
    *,
    review_input: object | None = None,
    previous_findings: tuple[Finding, ...] = (),
) -> QaSubflowOutcome:
    """Execute the full QA-subflow and return a structured outcome.

    Steps:
    1. Resolve ``target`` to an internal ``VerifyTarget`` (fail-closed
       on unknown target_type).
    2. Select layers via ``select_layers(qa_context)``.
    3. Execute each selected layer in order; wrap unexpected exceptions
       in ``LayerExecutionError`` and aggregate as BLOCKING findings.
       Layer 2 (LLM_EVALUATOR) runs three distinct reviewers (W1);
       each produces its own ``LayerResult`` and its own envelope.
    4. Write a QA artefact via ``ArtifactManager`` for each executed layer.
    5. Run the policy engine over all collected ``LayerResult`` instances.
    6. Write the policy decision artefact.
    7. Return a ``QaSubflowOutcome`` carrying the verdict, full
       ``VerifyDecision``, artifact filenames, attempt counter, and
       optional remediation feedback (AG3-026 Pass-2 §Befund-A).

    Cross-BC callers (e.g. ``agentkit.backend.implementation``) MUST use
    ``outcome.verdict`` for the PASS/FAIL gate and feed
    ``outcome.decision`` into the FK-69 recording path
    (``record_layer_artifacts`` / ``record_verify_decision``) -- no
    second layer-execution is needed.

    Args:
        ctx: Run-time context bundle (run_id, story_dir, phase_envelope,
            attempt).
        story_id: Story display-ID (e.g. ``AG3-042``).
        qa_context: Invocation context that controls layer selection.
        target: Typed reference to the artefact under review.
        review_input: Optional ``Layer2ReviewInput`` with the four FK-27
            text inputs for Layer-2 reviewers (story_spec, diff_summary,
            concept_excerpt, handover). When ``None``, a default empty
            ``Layer2ReviewInput()`` is used (Layer-2 reviewers will emit
            a MAJOR ``layer2_input.missing`` finding). Pass a populated
            instance once Workers produce handover artefacts (THEME-009).
        previous_findings: Findings from the prior remediation round (the
            state owner / phase handler carries them forward). In a
            remediation context they are matched against this round's
            findings by :class:`FindingResolutionAssessor` (FK-34 / DK-04
            §4.6); a still-open (NOT_RESOLVED / PARTIALLY_RESOLVED) previous
            finding sets ``closure_blocked`` (AG3-041 §2.1.6). Empty in the
            initial round.

    Returns:
        ``QaSubflowOutcome`` with ``verdict``, ``decision``,
        ``artifact_refs``, ``attempt_nr``, ``qa_cycle_round`` and
        optional ``feedback``.

    Raises:
        VerifyTargetUnknownError: If the target's artifact_class
            cannot be mapped to a ``VerifyTargetType``.
    """
    self = system
    # Step 1: Resolve target (fail-closed on unknown type).
    verify_target = self._resolve_verify_target(target)

    # Step 1b: Normalise review_input -- default to empty when None.
    # Layer-2 reviewers require a Layer2ReviewInput instance (fail-closed).
    # Until Workers produce handover artefacts (THEME-009), pass empty
    # strings so reviewers emit MAJOR layer2_input.missing, not silent PASS.
    from agentkit.backend.verify_system.llm_evaluator.inputs import Layer2ReviewInput as _L2Input

    effective_review_input: _L2Input = (
        review_input
        if isinstance(review_input, _L2Input)
        else _L2Input()
    )

    # Step 1c: Resolve StoryContext via the injected query port (AG3-035
    # real drift fix). NO direct ``state_backend.store`` import anymore in
    # verify_system; the concrete adapter is wired in the composition_root
    # (BC topology: verify-system depends on the port, not on state_backend).
    # The no-op port returns None -> _execute_layer falls back to the IMPLEMENTATION stub.
    _story_ctx = self._load_story_context_for_qa(ctx.story_dir)

    implementation_gate = _evaluate_implementation_terminality_precondition(
        self,
        ctx=ctx,
        story_id=story_id,
        story_ctx=_story_ctx,
        qa_context=qa_context,
    )
    if implementation_gate is not None:
        return implementation_gate

    # AG3-018 (FK-24 §24.3.4 Mode-Profil): in ``mode == fast`` the QA-subflow
    # degenerates to Layer 1 (structural) + the hard tests-green floor and
    # SKIPS Layers 2 (LLM), 3 (adversarial), 4 (policy), the Sonar gate AND
    # the feedback/remediation loop. The floor is non-disableable: a red test
    # (or an unconfirmable result) is a fail-closed FAIL (NO ERROR BYPASSING).
    if _is_fast_mode(_story_ctx):
        return self._run_fast_floor(
            ctx=ctx,
            story_id=story_id,
            story_ctx=_story_ctx,
        )

    # Step 2: Select layers.
    layer_kinds = select_layers(qa_context)

    # Step 3 + 4: Execute layers in order and write artefacts.
    layer_results: list[LayerResult] = []
    artifact_refs_written: list[str] = []
    now_str = _qa.utc_now_iso()

    # AG3-041 §2.1.7: drive the QA-cycle lifecycle. First call (no active
    # cycle) -> start_cycle (round 1, epoch 1). Remediation context with an
    # active cycle -> advance_qa_cycle (round/epoch +1, recompute
    # fingerprint, invalidate the 11/12 cycle-bound artefacts, FK-27
    # §27.2.3). The resulting identities are embedded into every QA artefact
    # written below. When no phase-envelope view is present (idle / legacy
    # callers), fall back to the previously-supplied fields (no cycle).
    cycle_state = _qa.resolve_qa_cycle_state(
        self.qa_cycle_lifecycle, ctx, story_id, qa_context
    )
    qa_cycle_fields = _qa.qa_cycle_state_to_fields(cycle_state)

    # Step 3 + 4 (extracted, S3776): execute the data layers in order. The gate
    # short-circuit decision and the context-sufficiency artefact are surfaced;
    # ``layer_results`` / ``artifact_refs_written`` are appended in place. The
    # break/continue/gate semantics are IDENTICAL to the prior inline loop.
    layer_loop = _execute_data_layers(
        self,
        layer_kinds=layer_kinds,
        ctx=ctx,
        story_id=story_id,
        now_str=now_str,
        qa_cycle_fields=qa_cycle_fields,
        cycle_state=cycle_state,
        story_ctx=_story_ctx,
        effective_review_input=effective_review_input,
        previous_findings=previous_findings,
        layer_results=layer_results,
        artifact_refs_written=artifact_refs_written,
    )
    sonar_fail_decision = layer_loop.sonar_fail_decision
    context_sufficiency_artifact = layer_loop.context_sufficiency_artifact

    # AG3-069 (FK-05 §5.10/§5.11, FK-37 §37.1.3, AC5/AC12): for
    # integration_stabilization stories produce the REAL stability_gate Layer-4
    # result BEFORE the policy decision (only when no Sonar short-circuit). The
    # gate evaluates reached integration_targets, undeclared_surface and budget,
    # produces a Layer-4 LayerResult the PolicyEngine aggregates AND persists the
    # gate verdict the closure precondition reads. Gated on the IS contract so
    # standard stories are completely unaffected (CORE PRINCIPLE).
    if sonar_fail_decision is None:
        _maybe_produce_is_stability_gate(
            self,
            ctx=ctx,
            story_id=story_id,
            story_ctx=_story_ctx,
            layer_results=layer_results,
        )

    # Step 5: Policy decision. On a Sonar fail-closed short-circuit the
    # gate's BLOCKING SYSTEM finding is authoritative (FK-33 §33.6.3): no
    # policy aggregation, no decision.json.
    if sonar_fail_decision is not None:
        decision = sonar_fail_decision
    else:
        # FIX-A (FK-33 §33.7): the PRODUCTION path passes the EFFECTIVE
        # story type (the SAME one the layers were executed under, see
        # _execute_layer) + max_layer_reached + ARE activation so the
        # registry-bound fail-closed missing-stage check ALWAYS runs and the
        # FK-33 §33.7.3 per-story-type threshold is ALWAYS used. The scalar
        # fallback (no missing-stage check) is unreachable on this path:
        # _effective_story_type returns IMPLEMENTATION when no StoryContext
        # resolved, exactly mirroring the layer-execution stub, so an
        # unresolved context fails CLOSED through the registry path instead
        # of silently downgrading to the scalar threshold (no two-truth
        # threshold, no fail-open edge).
        decision = self.policy_engine.decide(
            layer_results,
            story_type=_effective_story_type(_story_ctx),
            max_layer_reached=_max_layer_reached(layer_results),
            # FIX-A: pass the EXACT executed-layer set so the fail-closed
            # missing-stage check honours non-contiguous routes (FK-27 §27.3:
            # Exploration runs Layer 2 + Layer 4 and SKIPS Layer 1, so a
            # Layer-1 stage must NOT be reported missing there). Without this
            # the registry path would over-block the legitimate exploration
            # route once the scalar fallback is removed.
            traversed_layers=_traversed_layers(layer_kinds),
            are_enabled=self._structural_are_enabled(),
            context_sufficiency_artifact=context_sufficiency_artifact,
            # AG3-069 (FK-37 §37.1.3, AC12): thread the implementation_contract so
            # the registry-bound fail-closed missing-stage check requires the IS
            # Layer-4 stages (stability_gate + integration_target_matrix_passed)
            # for integration_stabilization. A normal QA PASS is then NOT
            # sufficient for IS closure — the IS gate result MUST be produced.
            implementation_contract=_effective_implementation_contract(_story_ctx),
        )
        # Step 6: Write policy decision artefact.
        decision_ref = self._write_policy_artifact(
            decision=decision,
            ctx=ctx,
            story_id=story_id,
            now_str=now_str,
            qa_cycle_fields=qa_cycle_fields,
        )
        artifact_refs_written.append(decision_ref)

    # Build internal result detail (retained for internal diagnostics).
    all_findings = tuple(f for lr in layer_results for f in lr.findings)
    _detail = _QaSubflowExecutionResult(
        verdict=decision.verdict,
        stage_results=tuple(layer_results),
        artifact_refs_written=tuple(artifact_refs_written),
        blocking_failures=sum(
            1 for f in all_findings if f.severity == Severity.BLOCKING
        ),
        major_failures=sum(
            1 for f in all_findings if f.severity == Severity.MAJOR
        ),
        minor_failures=sum(
            1 for f in all_findings if f.severity == Severity.MINOR
        ),
    )

    logger.info(
        "run_qa_subflow completed: story=%s qa_context=%s verdict=%s "
        "target_type=%s layers_run=%d",
        story_id,
        qa_context,
        decision.verdict,
        verify_target.target_type,
        len(layer_results),
    )

    # Step 7: Build remediation feedback when FAIL (AG3-026 Pass-2 §Befund-A).
    # FK-34 / DK-04 §4.6 (AG3-041 §2.1.5/§2.1.6): in a remediation context
    # the FindingResolutionAssessor classifies each previous-round finding
    # (FULLY/PARTIALLY/NOT_RESOLVED) against this round; the resolution map
    # feeds build_feedback so has_open_findings() drives closure_blocked.
    from agentkit.backend.verify_system.remediation.feedback import build_feedback
    from agentkit.backend.verify_system.remediation.finding_resolution import (
        resolution_map_has_open_findings,
    )

    # AG3-043 E5: the deterministic assessor is the baseline; the Layer-2
    # LLM resolution verdicts (carried in each Layer-2 LayerResult.metadata)
    # are merged into the SAME map so a still-open LLM verdict
    # (partially_resolved / not_resolved) reaches the canonical closure
    # block -- not just the audit metadata. Fail-closed merge: the more-open
    # status wins per (layer, check) key.
    resolution_map = _qa.merge_llm_finding_resolutions(
        _qa.assess_finding_resolution(
            qa_context, previous_findings, decision.all_findings
        ),
        tuple(decision.layer_results),
    )
    mandatory_target_findings = _mandatory_target_feedback_findings(
        self,
        story_id=story_id,
        run_id=ctx.run_id,
        qa_cycle_round=cycle_state.round,
    )
    feedback = build_feedback(
        decision,
        story_id,
        ctx.attempt,
        finding_resolution=resolution_map,
        extra_blocking_findings=mandatory_target_findings,
    )

    # Step 8: AG3-041 §2.1.7 -- run the remediation loop controller AFTER
    # the policy engine (or the Sonar fail-closed decision, FK-27 §27.6a.2).
    # PASS -> CONTINUE_TO_CLOSURE; FAIL + round < max -> CONTINUE_REMEDIATION;
    # FAIL + round >= max -> ESCALATE (hard, FK-27 §27.2.2
    # max_rounds_exceeded). escalated forces verdict=FAIL. The Sonar
    # fail-closed verdict traverses the SAME loop (no bypass, no fail-open).
    #
    # FIX-5 (FK-27 §27.4.2/§27.4.5): an ``impact.violation`` BLOCKING FAIL
    # routes DIRECTLY to ESCALATED -- "escalation to a human, no
    # return jump", no worker-feedback loop. The structural layer stamps
    # ``metadata["escalated"]=True`` (checker.py); detect it here and force
    # immediate escalation BEFORE/independent of the remediation-round
    # ceiling, so an impact violation never loops through normal remediation.
    escalated = _layer_escalation_requested(decision.layer_results) or (
        _qa.evaluate_escalation(
            self.remediation_loop_controller,
            cycle_state,
            decision.verdict,
        )
    )

    # closure_blocked: in a remediation context with at least one open
    # (NOT_RESOLVED / PARTIALLY_RESOLVED) previous finding (FK-34 §34.9.4 /
    # DK-04 §4.6, AG3-041 §2.1.6). Derived DIRECTLY from the finding-
    # resolution assessment and INDEPENDENT of the policy verdict: a PASS
    # verdict produces no feedback object, but a still-open (e.g.
    # PARTIALLY_RESOLVED) previous finding must still block closure
    # (no fail-open toward closure). The feedback object is not the source
    # of truth here.
    closure_blocked = resolution_map_has_open_findings(resolution_map)

    # AG3-044 (FK-27 §27.6 / FK-48 §48.2): after Layer 2 yields BLOCKING
    # findings the Layer-3 adversarial spawn is REQUESTED on the real QA
    # path -- derive mandatory targets from those findings, materialise the
    # protected sandbox + ``ADVERSARIAL_TEST_SANDBOX`` envelope, and carry
    # the typed spawn orders out. Only when Layer 3 was routed (IMPLEMENTATION
    # context); Exploration / fast skip Layer 3 and produce no spawn order.
    adversarial_spawn = self._derive_adversarial_spawn(
        ctx, story_id, layer_kinds, layer_results
    )

    # Step 9: Return QaSubflowOutcome (public DTO, AK11 / §2.1.3). The cycle
    # is always resolved (FK-27 §27.2.2 idle -> awaiting_qa), so all four
    # identity fields are surfaced for the state owner to persist.
    return QaSubflowOutcome(
        verdict=PolicyVerdict.FAIL if escalated else decision.verdict,
        decision=decision,
        artifact_refs=tuple(artifact_refs_written),
        attempt_nr=ctx.attempt,
        qa_cycle_round=cycle_state.round,
        feedback=feedback,
        qa_cycle_id=cycle_state.qa_cycle_id,
        evidence_epoch=cycle_state.evidence_epoch,
        evidence_fingerprint=cycle_state.evidence_fingerprint,
        escalated=escalated,
        closure_blocked=closure_blocked,
        adversarial_spawn=adversarial_spawn,
    )


def _layer_escalation_requested(layer_results: tuple[LayerResult, ...]) -> bool:
    """Whether any layer stamped an immediate-escalation request (FIX-5).

    FK-27 §27.4.2/§27.4.5: the structural layer sets
    ``metadata["escalated"]=True`` when an ``escalated`` stage
    (``impact.violation``) FAILs BLOCKING. Such a finding must escalate
    immediately to a human -- it must NOT traverse the normal remediation loop.
    """
    return any(lr.metadata.get("escalated") is True for lr in layer_results)


def _mandatory_target_feedback_findings(
    system: VerifySystem,
    *,
    story_id: str,
    run_id: str,
    qa_cycle_round: int,
) -> tuple[Finding, ...]:
    """Load Layer-3 mandatory target results and map unmet targets for feedback.

    Fail-closed (AG3-067 AC8 remediation): only a GENUINELY-absent adversarial
    artifact (:class:`ArtifactNotFoundError`) means "no mandatory targets" — the
    adversarial stage did not run or produced nothing. Any OTHER failure (broken
    envelope/payload access, missing ``artifact_manager`` precondition) is a
    broken state that must NOT disappear as "no targets" (that would silently drop
    a BLOCKING mandatory target the remediation loop needs); it is surfaced as a
    hard :class:`MandatoryTargetReadError` instead of being swallowed.
    """
    if qa_cycle_round < 2:
        return ()
    from agentkit.backend.artifacts import ArtifactNotFoundError
    from agentkit.backend.core_types.qa_artifact_names import ADVERSARIAL_STAGE
    from agentkit.backend.verify_system.errors import MandatoryTargetReadError
    from agentkit.backend.verify_system.remediation.feedback import (
        mandatory_target_findings_from_adversarial,
    )

    try:
        envelope = system.artifact_manager.read_latest(
            story_id=story_id,
            run_id=run_id,
            artifact_class=ArtifactClass.QA,
            stage=ADVERSARIAL_STAGE,
        )
    except ArtifactNotFoundError:
        # Genuinely absent adversarial.json -> no mandatory targets (not an error).
        return ()
    except Exception as exc:  # noqa: BLE001 -- fail-closed: broken read must surface
        raise MandatoryTargetReadError(
            "Failed to read the Layer-3 adversarial artifact for mandatory-target "
            f"feedback (story={story_id!r}, run={run_id!r}, stage={ADVERSARIAL_STAGE!r}): "
            f"{type(exc).__name__}: {exc}. A broken adversarial artifact must not "
            "silently drop a mandatory target (FAIL-CLOSED)."
        ) from exc
    # AC8 remediation r2: a PRESENT envelope with a None/broken (non-mapping)
    # payload is a broken artifact, NOT "no targets". ``payload or {}`` would
    # mask it into an empty dict and silently drop any mandatory target — that
    # is exactly the FAIL-CLOSED hole the genuinely-absent path is meant to
    # exclude. Only ``ArtifactNotFoundError`` (handled above) means "no targets";
    # a present-but-unusable payload fails closed here.
    payload = envelope.payload
    if not isinstance(payload, Mapping):
        raise MandatoryTargetReadError(
            "The Layer-3 adversarial artifact is present but its payload is "
            f"unusable (story={story_id!r}, run={run_id!r}, "
            f"stage={ADVERSARIAL_STAGE!r}): expected a mapping, got "
            f"{type(payload).__name__}. A present-but-broken adversarial payload "
            "must not silently drop a mandatory target (FAIL-CLOSED)."
        )
    return mandatory_target_findings_from_adversarial(dict(payload))


def _effective_story_type(story_ctx: object | None) -> StoryType:
    """Return the EFFECTIVE ``StoryType`` driving both layer execution and policy.

    FIX-A (fail-closed): the production path must never re-enter the policy
    engine's scalar fallback (which runs NO registry-bound missing-stage check,
    FK-33 §33.7 -- a fail-open edge). The effective story type is the SAME one
    ``_execute_layer`` commits to: the resolved ``StoryContext.story_type`` when
    a context resolved, otherwise the ``IMPLEMENTATION`` stub used for the layer
    run itself. Returning a concrete type unconditionally guarantees
    ``PolicyEngine.decide`` always takes the registry path (per-story-type
    threshold FK-33 §33.7.3 + fail-closed missing-stage check), consistent with
    the type the layers were evaluated under. There is no genuinely-unknown
    story type on this path: layer execution already chose IMPLEMENTATION when
    unresolved, so the policy decision uses the identical effective type rather
    than silently downgrading to the scalar threshold.
    """
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.types import StoryType

    if isinstance(story_ctx, StoryContext):
        return story_ctx.story_type
    return StoryType.IMPLEMENTATION


def _effective_implementation_contract(
    story_ctx: object | None,
) -> ImplementationContract | None:
    """Return the EFFECTIVE ``implementation_contract`` for the policy decision.

    AG3-069 (FK-37 §37.1.3): the resolved ``StoryContext.implementation_contract``
    drives the registry-bound contract filter in ``PolicyEngine.decide``. When no
    context resolved (or it carries no contract), ``None`` is returned — the
    standard behaviour (IS stages excluded), so a non-IS run is unaffected.
    """
    from agentkit.backend.story_context_manager.models import StoryContext

    if isinstance(story_ctx, StoryContext):
        return story_ctx.implementation_contract
    return None


def _maybe_produce_is_stability_gate(
    system: VerifySystem,
    *,
    ctx: VerifyContextBundle,
    story_id: str,
    story_ctx: object | None,
    layer_results: list[LayerResult],
) -> None:
    """Produce the stability_gate Layer-4 result for IS stories (AG3-069, AC5/AC12).

    No-op for standard stories (the contract gate). For
    integration_stabilization it runs the REAL stability_gate producer over the
    actually-touched surfaces (from the QA change-evidence port), appends the
    produced Layer-4 :class:`LayerResult` to ``layer_results`` (so the
    PolicyEngine aggregation consumes it and the registry-bound missing-stage
    check is satisfied), persists the gate verdict and emits the telemetry event.

    Args:
        system: The owning ``VerifySystem``.
        ctx: The run-time context bundle (run_id + story_dir).
        story_id: The story display id.
        story_ctx: The resolved ``StoryContext`` (or ``None``).
        layer_results: Mutable accumulator the produced gate result is appended to.
    """
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.types import ImplementationContract

    if not (
        isinstance(story_ctx, StoryContext)
        and story_ctx.implementation_contract
        is ImplementationContract.INTEGRATION_STABILIZATION
    ):
        return

    from agentkit.backend.integration_stabilization.stability_gate_producer import (
        produce_stability_gate_layer_result,
    )

    evidence = system.implementation_change_evidence_port.collect(ctx.story_dir)
    touched_paths = tuple(evidence.changed_files) if evidence.available else ()

    result = produce_stability_gate_layer_result(
        story_dir=ctx.story_dir,
        run_id=ctx.run_id,
        touched_paths=touched_paths,
        emitter=system.conformance_emitter,
        story_id=story_id,
        project_key=story_ctx.project_key,
    )
    layer_results.append(result)


def _max_layer_reached(layer_results: list[LayerResult]) -> int:
    """Derive the highest QA layer that produced a result (FK-33 §33.7.2)."""
    from agentkit.backend.story_context_manager.types import ImplementationContract
    from agentkit.backend.verify_system.stage_registry.registry import (
        is_integration_stabilization_stage,
    )

    registry = StageRegistry()
    reached: list[int] = []
    for stage_id in _produced_stage_ids(layer_results, registry):
        contract = (
            ImplementationContract.INTEGRATION_STABILIZATION
            if is_integration_stabilization_stage(stage_id)
            else None
        )
        stage = registry.stage_for_id(stage_id, implementation_contract=contract)
        if stage is not None:
            reached.append(stage.layer)
    return max(reached) if reached else 1


def _traversed_layers(layer_kinds: tuple[QALayerKind, ...]) -> frozenset[int]:
    """Return the EXACT set of QA layer numbers the route planned (FK-33 §33.7.2).

    Maps the routed :class:`QALayerKind` tuple to the layer numbers whose stages
    the policy engine should expect. The route is not always contiguous: the
    Exploration context runs Layer 2 + Layer 4 and SKIPS Layer 1, so its set is
    ``{2, 4}`` -- a Layer-1 stage is therefore not expected (and not reported
    missing) on that path.
    """
    registry = StageRegistry()
    return frozenset(_layer_number_for_kind(kind, registry) for kind in layer_kinds)


def _produced_stage_ids(
    layer_results: list[LayerResult],
    registry: StageRegistry,
) -> set[str]:
    """Return produced stage IDs from result names and registry metadata."""
    produced: set[str] = set()
    for result in layer_results:
        metadata_stage_ids = result.metadata.get("stage_ids")
        if isinstance(metadata_stage_ids, (list, tuple, set, frozenset)):
            produced.update(str(stage_id) for stage_id in metadata_stage_ids)
        for stage in registry.stages:
            if result.layer == stage.stage_id or result.layer == _legacy_result_name(stage.stage_id):
                produced.add(stage.stage_id)
    return produced


def _legacy_result_name(stage_id: str) -> str:
    """Return the legacy LayerResult name for a stage ID."""
    if stage_id.endswith("_impl"):
        return stage_id.removesuffix("_impl")
    return stage_id


def _layer_number_for_kind(kind: QALayerKind, registry: StageRegistry) -> int:
    """Resolve a routed QA kind to its layer via the stage registry."""
    if kind is QALayerKind.STRUCTURAL:
        stage = registry.stage_for_id("artifact.protocol")
    elif kind is QALayerKind.SONARQUBE_GATE:
        stage = registry.stage_for_id("sonarqube_gate")
    elif kind is QALayerKind.LLM_EVALUATOR:
        stage = next((s for s in registry.stages if s.kind is StageKind.LLM_EVALUATION), None)
    elif kind is QALayerKind.ADVERSARIAL:
        stage = registry.stage_for_id("adversarial")
    else:
        stage = registry.stage_for_id("policy")
    if stage is None:  # pragma: no cover - canonical registry invariant
        msg = f"cannot resolve layer for routed QA kind {kind!r}"
        raise ValueError(msg)
    return stage.layer


def _is_fast_mode(story_ctx: object | None) -> bool:
    """Whether the resolved ``StoryContext`` runs in fast mode (FK-24 §24.3.3).

    The fast/standard ``mode`` axis is decoupled from ``execution_route``
    (FK-24 §24.3.3). Returns ``False`` when no ``StoryContext`` resolved (the
    no-op port path / tests without a persisted context): a missing mode is the
    standard full-subflow default, never an accidental fast skip.

    Args:
        story_ctx: The resolved ``StoryContext`` (or ``None``).

    Returns:
        ``True`` iff a ``StoryContext`` resolved AND its ``mode`` is fast.
    """
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.story_model import WireStoryMode

    return isinstance(story_ctx, StoryContext) and story_ctx.mode is WireStoryMode.FAST


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
