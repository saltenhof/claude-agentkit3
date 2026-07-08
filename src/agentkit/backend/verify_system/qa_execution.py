"""QA-subflow execution orchestrates verification without owning layer-specific responsibilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.core_types import PolicyVerdict, QaContext
from agentkit.backend.verify_system.contract import (
    QaSubflowOutcome,
    VerifyContextBundle,
    _QaSubflowExecutionResult,
)
from agentkit.backend.verify_system.implementation_evidence_precondition import (
    _evaluate_implementation_terminality_precondition,
)
from agentkit.backend.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
)
from agentkit.backend.verify_system.qa_cycle import integration as _qa
from agentkit.backend.verify_system.remediation_feedback import (
    _layer_escalation_requested,
    _mandatory_target_feedback_findings,
)
from agentkit.backend.verify_system.routed_layer_execution import _execute_data_layers
from agentkit.backend.verify_system.routing import select_layers
from agentkit.backend.verify_system.stability_gate_verdict import (
    _maybe_produce_is_stability_gate,
)
from agentkit.backend.verify_system.stage_coverage_mapping import (
    _max_layer_reached,
    _traversed_layers,
)
from agentkit.backend.verify_system.story_contract_resolution import (
    _effective_implementation_contract,
    _effective_story_type,
    _is_fast_mode,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agentkit.backend.artifacts import ArtifactReference
    from agentkit.backend.verify_system.system import VerifySystem


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
       optional remediation feedback (AG3-026 Pass-2 finding A).

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

    # Step 7: Build remediation feedback when FAIL (AG3-026 Pass-2 finding A).
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
