"""Top-Surface of the verify-system Bounded Context.

``VerifySystem`` is the Capability-A-Top-Komponente of the BC
``verify-system`` (FK-07 §7.4.2, FK-27, ``concept/_meta/bc-cut-decisions.md``
§"BC 2: verify-system"). Cross-BC callers (e.g. ``agentkit.implementation``)
MUST go through this facade and MUST NOT import sub-components such as
``policy_engine.PolicyEngine`` or ``adversarial_orchestrator.challenger.
AdversarialChallenger`` directly (Sichtbarkeitsregel, AC001).

Normative contract (BC-Cut + FK-27 + formal.verify.commands):
``run_qa_subflow(ctx, story_id, qa_context, target) -> QaSubflowOutcome``
(AG3-026 Pass-2 Befund A: was PolicyVerdict).

Quelle:
  - AG3-026 §2.1.1 -- VerifySystem-Top-Klasse
  - ``concept/_meta/bc-cut-decisions.md §BC 2 verify-system``
  - ``concept/_meta/bc-cut-decisions.md §QA-Subflow-Vertrag``
  - FK-27 §27.3 (QA-Subflow-Top)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from agentkit.artifacts import (
    ArtifactEnvelope,
    ArtifactManager,
    ArtifactReference,
    EnvelopeStatus,
    Producer,
    ProducerId,
)
from agentkit.core_types import ArtifactClass, PolicyVerdict, QaContext
from agentkit.verify_system._artifact_specs import (
    ARTIFACT_CLASS_TO_TARGET_TYPE as _ARTIFACT_CLASS_TO_TARGET_TYPE,
)
from agentkit.verify_system._artifact_specs import (
    LAYER_1_ARTIFACTS as _LAYER_1_ARTIFACTS,
)
from agentkit.verify_system._artifact_specs import (
    LAYER_2_SPECS as _LAYER_2_SPECS,
)
from agentkit.verify_system._artifact_specs import (
    LAYER_3_ARTIFACTS as _LAYER_3_ARTIFACTS,
)
from agentkit.verify_system._artifact_specs import (
    POLICY_ARTIFACT_SPEC as _POLICY_ARTIFACT_SPEC,
)
from agentkit.verify_system._artifact_specs import (
    SONARQUBE_GATE_ARTIFACTS as _SONARQUBE_GATE_ARTIFACTS,
)
from agentkit.verify_system._artifact_specs import _LayerArtifactSpec
from agentkit.verify_system.adversarial_orchestrator.challenger import (
    AdversarialChallenger,
)
from agentkit.verify_system.contract import (
    QaSubflowOutcome,
    VerifyContextBundle,
    VerifyTarget,
    _QaSubflowExecutionResult,
)
from agentkit.verify_system.errors import (
    LayerExecutionError,
    VerifySystemError,
    VerifyTargetUnknownError,
)
from agentkit.verify_system.llm_evaluator.reviewer import (
    DocFidelityReviewer,
    QaReviewReviewer,
    SemanticReviewer,
)
from agentkit.verify_system.policy_engine.engine import PolicyEngine, VerifyDecision
from agentkit.verify_system.protocols import (
    Finding,
    LayerResult,
    QALayer,
    RunScope,
    Severity,
    StoryContextQueryPort,
    TrustClass,
)
from agentkit.verify_system.qa_cycle import integration as _qa
from agentkit.verify_system.routing import QALayerKind, select_layers
from agentkit.verify_system.sonarqube_gate.port import (
    ABSENT_SONAR_GATE_PORT,
    SonarGateInputPort,
)
from agentkit.verify_system.sonarqube_gate.stage_runner import (
    SonarStageResult,
    run_sonarqube_gate_stage,
)
from agentkit.verify_system.structural.checker import StructuralChecker

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.qa_cycle.invalidation import (
        ArtifactInvalidationSink,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _NullStoryContextPort:
    """No-op ``StoryContextQueryPort``: liefert immer ``None``.

    Default fuer ``VerifySystem`` ohne injizierten state-backed Adapter
    (Testpfad ohne DB). Erhaelt das historische Fallback-Verhalten auf den
    IMPLEMENTATION-Stub in ``_execute_layer`` (AG3-035).
    """

    def load(self, story_dir: Path) -> StoryContext | None:
        """Return ``None``; der No-op-Port ignoriert ``story_dir``.

        Args:
            story_dir: Story-Arbeitsverzeichnis (vom No-op-Port nicht konsumiert).
        """
        del story_dir  # No-op-Port nutzt den Pfad nicht (Protocol-Param, S1172).
        return None

    def resolve_run_scope(self, story_dir: Path) -> RunScope | None:
        """Return ``None``; ohne State-Backend ist keine Run-Korrelation bekannt.

        Args:
            story_dir: Story-Arbeitsverzeichnis (vom No-op-Port nicht konsumiert).
        """
        del story_dir  # No-op-Port nutzt den Pfad nicht (Protocol-Param, S1172).
        return None


_NULL_STORY_CONTEXT_PORT: StoryContextQueryPort = _NullStoryContextPort()


@dataclass(frozen=True)
class VerifySystem:
    """Top-Surface of the verify-system Capability-BC.

    Holds the sub-components that the BC composes internally. Cross-BC
    consumers obtain instances through :meth:`create_default` and call
    the published methods of this class. The sub-component fields are
    intentionally typed against the internal classes; consumers must
    not reach into them.

    W1: Layer 2 is now three distinct reviewers (``layer_2a``,
    ``layer_2b``, ``layer_2c``) each producing its own ``LayerResult``
    with distinct findings. The backward-compatible ``layer_2`` property
    returns ``layer_2a`` for test-double wiring.

    Attributes:
        layer_1: Layer-1 deterministic structural checker.
            Must satisfy :class:`QALayer` protocol.
        layer_2a: Layer-2a QA-review reviewer (Testqualitaet/Coverage).
        layer_2b: Layer-2b semantic reviewer (Konzept-Treue/Naming).
        layer_2c: Layer-2c doc-fidelity reviewer (Docstrings/ADR).
        layer_3: Layer-3 adversarial orchestrator.
            Must satisfy :class:`QALayer` protocol.
        policy_engine: Layer-4 deterministic aggregator.
        artifact_manager: ArtifactManager for writing QA artefacts.
        story_context_port: Injizierter Read-Port zum Aufloesen des
            ``StoryContext`` (AG3-035). Default ist ein No-op-Port; der
            produktive state-backed Adapter wird via
            ``composition_root.build_verify_system`` verdrahtet. Eliminiert den
            direkten ``state_backend.store``-Import in ``run_qa_subflow``.
        adversarial_challenger: Backward-compatible alias for ``layer_3``;
            kept to avoid breaking AG3-023/AG3-024 consumers.
        sonar_gate_port: Read-port resolving the SonarQube-Green-Gate
            inputs (FK-33 §33.6, AG3-052). Default is the absent-Sonar
            port (``sonarqube.available == false`` => stage SKIP). The
            productive adapter (talking to ``integrations.sonar`` + config)
            is wired via the composition root.
    """

    layer_1: QALayer
    layer_2a: QALayer
    layer_2b: QALayer
    layer_2c: QALayer
    layer_3: QALayer
    policy_engine: PolicyEngine
    artifact_manager: ArtifactManager
    story_context_port: StoryContextQueryPort = _NULL_STORY_CONTEXT_PORT
    sonar_gate_port: SonarGateInputPort = ABSENT_SONAR_GATE_PORT
    qa_cycle_lifecycle: _qa.QaCycleLifecycle = field(
        default_factory=_qa.QaCycleLifecycle
    )
    remediation_loop_controller: _qa.RemediationLoopController = field(
        default_factory=_qa.RemediationLoopController
    )

    @property
    def layer_2(self) -> QALayer:
        """Backward-compatible alias for ``layer_2a``.

        Returns:
            ``layer_2a`` (QaReviewReviewer by default).
        """
        return self.layer_2a

    @property
    def adversarial_challenger(self) -> QALayer:
        """Backward-compatible alias for ``layer_3`` (AG3-023/AG3-024 compat).

        Returns:
            The QALayer instance held as ``layer_3``.
        """
        return self.layer_3

    @classmethod
    def create_default(
        cls,
        *,
        artifact_manager: ArtifactManager,
        max_major_findings: int = 0,
        max_feedback_rounds: int | None = None,
        story_context_port: StoryContextQueryPort | None = None,
        sonar_gate_port: SonarGateInputPort | None = None,
        invalidation_sink: ArtifactInvalidationSink | None = None,
    ) -> VerifySystem:
        """Construct a ``VerifySystem`` with default sub-components.

        Builds all sub-components with sensible defaults.
        ``artifact_manager`` ist **Pflicht-Argument** (AG3-026 §2.1.4 +
        Re-Review-Befund 3): ein fehlender ArtifactManager war
        Story-explizit als Fail-closed-Pfad markiert; eine stille
        No-Op-Variante hatte unbemerkt QA-Wahrheit verworfen.

        Args:
            artifact_manager: ``ArtifactManager`` fuer Artefakt-Writes.
                **Pflicht**. Aufrufer, die einen Test-Stub brauchen,
                liefern einen Recording-Test-Double; produktive Aufrufer
                nutzen ``bootstrap.composition_root.build_verify_system``.
            max_major_findings: Threshold for the policy engine. Mirrors
                :class:`PolicyEngine` -- MAJOR findings beyond this count
                turn into blocking findings (FK-27 §27.4.2 / §27.7.2).
            max_feedback_rounds: Ceiling for the subflow-internal remediation
                loop (FK-03 §3.4.2 / FK-38; resolved from the pipeline config by
                ``build_verify_system``). ``None`` => the controller's default
                (3). The :class:`RemediationLoopController` is the hard owner of
                the ceiling — it is NOT bypassable (NO ERROR BYPASSING).
            story_context_port: Optionaler ``StoryContextQueryPort`` (AG3-035).
                Wenn ``None``, wird der No-op-Port genutzt (Fallback auf den
                IMPLEMENTATION-Stub in ``_execute_layer``). Produktive Aufrufer
                reichen den state-backed Adapter via
                ``composition_root.build_verify_system`` ein.
            sonar_gate_port: Optionaler ``SonarGateInputPort`` (AG3-052,
                FK-33 §33.6). Wenn ``None``, wird der Absent-Sonar-Port
                genutzt (``sonarqube.available == false`` => Stage SKIP).
            invalidation_sink: Optionaler produktiver
                ``ArtifactInvalidationSink`` (FK-27 §27.2.3 / AG3-041 §2.1.3):
                emittiert pro ``stale/``-Move ein ``artifact_invalidated``-
                Telemetrie-Event. ``None`` => No-op-Sink (Testpfad ohne
                verdrahtete Telemetrie). Produktive Aufrufer reichen den
                telemetrie-gebundenen Sink via
                ``composition_root.build_verify_system`` ein.

        Returns:
            A frozen ``VerifySystem`` with default-configured sub-components.

        Raises:
            VerifySystemError: when ``artifact_manager`` is ``None``.
        """
        if artifact_manager is None:
            raise VerifySystemError(
                "VerifySystem.create_default() requires an ArtifactManager "
                "(AG3-026 §2.1.4 fail-closed). Use "
                "agentkit.bootstrap.composition_root.build_verify_system "
                "for the wired default.",
            )
        resolved_port = story_context_port or _NULL_STORY_CONTEXT_PORT
        resolved_sonar_port = sonar_gate_port or ABSENT_SONAR_GATE_PORT
        # AG3-015 / FK-44 §44.4.2: the QA layers materialize their prompts via
        # PromptRuntime.materialize_prompt and audit them via the
        # ArtifactManager. Both dependencies are injected here so no layer
        # reaches into prompt-runtime sub-modules or state_backend.store.
        return cls(
            layer_1=StructuralChecker(),
            layer_2a=QaReviewReviewer(
                artifact_manager=artifact_manager,
                story_context_port=resolved_port,
            ),
            layer_2b=SemanticReviewer(
                artifact_manager=artifact_manager,
                story_context_port=resolved_port,
            ),
            layer_2c=DocFidelityReviewer(
                artifact_manager=artifact_manager,
                story_context_port=resolved_port,
            ),
            layer_3=AdversarialChallenger(
                artifact_manager=artifact_manager,
                story_context_port=resolved_port,
            ),
            policy_engine=PolicyEngine(max_major_findings=max_major_findings),
            artifact_manager=artifact_manager,
            story_context_port=resolved_port,
            sonar_gate_port=resolved_sonar_port,
            remediation_loop_controller=(
                _qa.RemediationLoopController(
                    max_feedback_rounds=max_feedback_rounds
                )
                if max_feedback_rounds is not None
                else _qa.RemediationLoopController()
            ),
            qa_cycle_lifecycle=(
                _qa.QaCycleLifecycle(invalidation_sink=invalidation_sink)
                if invalidation_sink is not None
                else _qa.QaCycleLifecycle()
            ),
        )

    # ------------------------------------------------------------------
    # Backward-compatible methods (AG3-023 / AG3-024 surface)
    # ------------------------------------------------------------------

    def policy_decision(
        self,
        layer_results: list[LayerResult],
    ) -> VerifyDecision:
        """Aggregate ``LayerResult`` instances into a final decision.

        Pure delegation to
        :meth:`agentkit.verify_system.policy_engine.engine.PolicyEngine.decide`.

        Args:
            layer_results: Results from all QA layers executed for this
                subflow round.

        Returns:
            Aggregated :class:`VerifyDecision` from the policy engine.
        """
        return self.policy_engine.decide(layer_results)

    def adversarial_layer(self) -> QALayer:
        """Return the adversarial QA layer (FK-27 Layer 3).

        The layer satisfies the :class:`QALayer` protocol and is
        intended to be appended to the QA-subflow layer list assembled
        by the caller.

        Returns:
            The :class:`AdversarialChallenger` instance held by this
            facade, typed against the public :class:`QALayer` protocol.
        """
        return self.layer_3

    # ------------------------------------------------------------------
    # New public method: AG3-026 Top-Surface
    # ------------------------------------------------------------------

    def run_qa_subflow(
        self,
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

        Cross-BC callers (e.g. ``agentkit.implementation``) MUST use
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
        # Step 1: Resolve target (fail-closed on unknown type).
        verify_target = self._resolve_verify_target(target)

        # Step 1b: Normalise review_input -- default to empty when None.
        # Layer-2 reviewers require a Layer2ReviewInput instance (fail-closed).
        # Until Workers produce handover artefacts (THEME-009), pass empty
        # strings so reviewers emit MAJOR layer2_input.missing, not silent PASS.
        from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput as _L2Input

        effective_review_input: _L2Input = (
            review_input
            if isinstance(review_input, _L2Input)
            else _L2Input()
        )

        # Step 1c: Resolve StoryContext via the injected query port (AG3-035
        # echter Drift-Fix). KEIN direkter ``state_backend.store``-Import mehr in
        # verify_system; der konkrete Adapter wird im composition_root verdrahtet
        # (BC-Topologie: verify-system haengt am Port, nicht an state_backend).
        # No-op-Port liefert None -> _execute_layer faellt auf IMPLEMENTATION-Stub.
        _story_ctx = self.story_context_port.load(ctx.story_dir)

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

        sonar_fail_decision: VerifyDecision | None = None
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
                    break
                continue

            self._run_data_layer_kind(
                kind=kind,
                ctx=ctx,
                story_id=story_id,
                now_str=now_str,
                qa_cycle_fields=qa_cycle_fields,
                effective_review_input=effective_review_input,
                story_ctx=_story_ctx,
                layer_results=layer_results,
                artifact_refs_written=artifact_refs_written,
            )

        # Step 5: Policy decision. On a Sonar fail-closed short-circuit the
        # gate's BLOCKING SYSTEM finding is authoritative (FK-33 §33.6.3): no
        # policy aggregation, no decision.json.
        if sonar_fail_decision is not None:
            decision = sonar_fail_decision
        else:
            decision = self.policy_engine.decide(layer_results)
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
        from agentkit.verify_system.remediation.feedback import build_feedback
        from agentkit.verify_system.remediation.finding_resolution import (
            resolution_map_has_open_findings,
        )

        resolution_map = _qa.assess_finding_resolution(
            qa_context, previous_findings, decision.all_findings
        )
        feedback = build_feedback(
            decision, story_id, ctx.attempt, finding_resolution=resolution_map
        )

        # Step 8: AG3-041 §2.1.7 -- run the remediation loop controller AFTER
        # the policy engine (or the Sonar fail-closed decision, FK-27 §27.6a.2).
        # PASS -> CONTINUE_TO_CLOSURE; FAIL + round < max -> CONTINUE_REMEDIATION;
        # FAIL + round >= max -> ESCALATE (hard, FK-27 §27.2.2
        # max_rounds_exceeded). escalated forces verdict=FAIL. The Sonar
        # fail-closed verdict traverses the SAME loop (no bypass, no fail-open).
        escalated = _qa.evaluate_escalation(
            self.remediation_loop_controller,
            cycle_state,
            decision.verdict,
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
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_sonarqube_gate_kind(
        self,
        *,
        ctx: VerifyContextBundle,
        story_id: str,
        now_str: str,
        qa_cycle_fields: dict[str, object],
        layer_results: list[LayerResult],
        artifact_refs_written: list[str],
    ) -> VerifyDecision | None:
        """Run the ``sonarqube_gate`` stage and update the run accumulators.

        Extracted from :meth:`run_qa_subflow` (S3776) without behaviour change.
        FK-33 §33.6 / §33.8.3 — classificatory Layer 1, sequenced AFTER
        adversarial, BEFORE policy. State-machine conformant
        (formal.deterministic-checks.state-machine):

        * NOT_APPLICABLE_FAST => stage DROPPED entirely (``stage_result is
          None``): no LayerResult, no artefact, no Sonar status; the fast
          QA-subflow terminates via the tests-green floor. Returns ``None`` so
          the caller simply continues.
        * NOT_APPLICABLE_UNAVAILABLE => SKIP marker; the gate ``LayerResult`` is
          appended so policy still aggregates over the other layers. Returns
          ``None``.
        * APPLICABLE green => PASS; the ``LayerResult`` is appended and the run
          continues to policy. Returns ``None``.
        * APPLICABLE fail-closed (red/stale/unreadable/0-or-multi ledger match)
          => route DIRECTLY to the terminal ``failed`` WITHOUT the policy engine
          and WITHOUT a decision artefact
          (invariant.passed-requires-sonarqube-gate-passed). Returns the FAIL
          ``VerifyDecision`` so the caller short-circuits the policy engine but
          STILL feeds the SAME remediation loop / escalation path
          (FK-27 §27.6a.2 — no loop bypass, no fail-open).

        Args:
            ctx: Run-time context bundle.
            story_id: Story display-ID.
            now_str: Pre-computed ISO timestamp for envelope writes.
            qa_cycle_fields: QA-cycle identity fields embedded in payloads.
            layer_results: Mutable accumulator of layer results (appended in
                place for the SKIP / PASS paths).
            artifact_refs_written: Mutable accumulator of artefact filenames
                (the gate envelope is appended; deliberately NO decision.json
                on the fail-closed path).

        Returns:
            The fail-closed ``VerifyDecision`` for an APPLICABLE gate FAIL, or
            ``None`` when the run should continue (dropped / SKIP / PASS).
        """
        stage_result = run_sonarqube_gate_stage(
            self.sonar_gate_port, story_id, ctx.story_dir
        )
        if stage_result is None:
            # NOT_APPLICABLE_FAST: drop the stage entirely.
            return None
        gate_result = stage_result.layer_result
        for spec in _SONARQUBE_GATE_ARTIFACTS:
            self._write_layer_envelope(
                spec=spec,
                result=gate_result,
                ctx=ctx,
                story_id=story_id,
                now_str=now_str,
                qa_cycle_fields=qa_cycle_fields,
            )
            artifact_refs_written.append(spec.filename)
        if stage_result.short_circuit_failed:
            return self._sonarqube_gate_failed_decision(
                stage_result=stage_result,
                layer_results=layer_results,
                story_id=story_id,
            )
        layer_results.append(gate_result)
        return None

    def _run_data_layer_kind(
        self,
        *,
        kind: QALayerKind,
        ctx: VerifyContextBundle,
        story_id: str,
        now_str: str,
        qa_cycle_fields: dict[str, object],
        effective_review_input: object | None,
        story_ctx: object | None,
        layer_results: list[LayerResult],
        artifact_refs_written: list[str],
    ) -> None:
        """Execute a non-gate data layer and write its envelope(s).

        Extracted from :meth:`run_qa_subflow` (S3776) without behaviour change.

        * ``LLM_EVALUATOR`` (W1): runs the three distinct Layer-2 reviewers,
          each producing its own ``LayerResult`` and its own envelope.
        * STRUCTURAL / ADVERSARIAL: resolves the single layer instance, executes
          it once and writes its single artefact spec(s).

        Args:
            kind: The (non-POLICY, non-SONARQUBE_GATE) layer kind to run.
            ctx: Run-time context bundle.
            story_id: Story display-ID.
            now_str: Pre-computed ISO timestamp for envelope writes.
            qa_cycle_fields: QA-cycle identity fields embedded in payloads.
            effective_review_input: Normalised Layer-2 review input.
            story_ctx: Pre-resolved ``StoryContext`` (or ``None``).
            layer_results: Mutable accumulator of layer results (appended in
                place).
            artifact_refs_written: Mutable accumulator of artefact filenames
                (appended in place).
        """
        if kind is QALayerKind.LLM_EVALUATOR:
            for layer_instance, spec in self._layer2_pairs():
                result = self._execute_layer(
                    layer_instance, ctx, story_id, kind,
                    review_input=effective_review_input,
                    story_context=story_ctx,
                )
                layer_results.append(result)
                self._write_layer_envelope(
                    spec=spec,
                    result=result,
                    ctx=ctx,
                    story_id=story_id,
                    now_str=now_str,
                    qa_cycle_fields=qa_cycle_fields,
                )
                artifact_refs_written.append(spec.filename)
            return

        layer_instance = self._layer_for_kind(kind)
        result = self._execute_layer(
            layer_instance, ctx, story_id, kind,
            review_input=effective_review_input,
            story_context=story_ctx,
        )
        layer_results.append(result)
        for spec in self._kind_to_single_artifacts(kind):
            self._write_layer_envelope(
                spec=spec,
                result=result,
                ctx=ctx,
                story_id=story_id,
                now_str=now_str,
                qa_cycle_fields=qa_cycle_fields,
            )
            artifact_refs_written.append(spec.filename)

    def _sonarqube_gate_failed_decision(
        self,
        *,
        stage_result: SonarStageResult,
        layer_results: list[LayerResult],
        story_id: str,
    ) -> VerifyDecision:
        """Build the direct fail-closed ``VerifyDecision`` for a gate FAIL.

        FK-33 §33.6.3 / formal.deterministic-checks state machine: an
        APPLICABLE ``sonarqube_gate`` fail-closed verdict (red gate,
        stale/unreadable attestation, 0/>1 ledger reconciliation) routes
        DIRECTLY to the terminal ``failed`` and must NEVER traverse
        ``policy_evaluated`` (invariant.passed-requires-sonarqube-gate-passed).
        Therefore the policy engine is NOT called and NO ``decision.json``
        policy artefact is written — the only verdict carrier is the gate
        envelope (already written by the caller).

        The returned ``VerifyDecision`` is assembled WITHOUT the aggregator (the
        gate's BLOCKING SYSTEM finding is authoritative). The caller still runs
        the SAME remediation loop / escalation path over this verdict
        (FK-27 §27.6a.2): a Sonar FAIL is a remediation FAIL like any other —
        it loops until green or escalates at ``max_feedback_rounds``, it does
        NOT bypass the loop.

        Args:
            stage_result: The fail-closed ``SonarStageResult`` from the gate.
            layer_results: Results of the layers executed before the gate.
            story_id: Story display-ID.

        Returns:
            A FAIL ``VerifyDecision`` reached without the policy engine.
        """
        gate_result = stage_result.layer_result
        all_results = (*tuple(layer_results), gate_result)
        all_findings = tuple(f for lr in all_results for f in lr.findings)
        blocking = tuple(
            f
            for f in all_findings
            if f.severity == Severity.BLOCKING and f.trust_class == TrustClass.SYSTEM
        )
        logger.info(
            "run_qa_subflow sonarqube_gate fail-closed (direct failed, no "
            "policy; routed into remediation loop): story=%s reason=%s",
            story_id,
            gate_result.metadata.get("failure_reason"),
        )
        return VerifyDecision(
            passed=False,
            verdict=PolicyVerdict.FAIL,
            layer_results=all_results,
            all_findings=all_findings,
            blocking_findings=blocking,
            summary=(
                "FAIL: SonarQube-Green-Gate fail-closed "
                f"({gate_result.metadata.get('failure_reason')!r}); routed "
                "directly to failed without policy aggregation, fed into the "
                "remediation loop (FK-33 §33.6.3 / FK-27 §27.6a.2)."
            ),
        )

    def _layer2_pairs(
        self,
    ) -> tuple[tuple[QALayer, _LayerArtifactSpec], ...]:
        """Return (reviewer, spec) pairs for the three Layer-2 reviewers.

        Returns:
            Tuple of (QALayer, _LayerArtifactSpec) for qa_review,
            semantic_review, doc_fidelity in that order.
        """
        return (
            (self.layer_2a, _LAYER_2_SPECS[0]),
            (self.layer_2b, _LAYER_2_SPECS[1]),
            (self.layer_2c, _LAYER_2_SPECS[2]),
        )

    def _resolve_verify_target(
        self,
        target: ArtifactReference,
    ) -> VerifyTarget:
        """Map ``ArtifactReference`` to an internal ``VerifyTarget``.

        Args:
            target: Public artefact reference.

        Returns:
            An internal ``VerifyTarget`` with a resolved ``VerifyTargetType``.

        Raises:
            VerifyTargetUnknownError: If the artifact_class has no known
                mapping to ``VerifyTargetType``.
        """
        target_type = _ARTIFACT_CLASS_TO_TARGET_TYPE.get(target.artifact_class)
        if target_type is None:
            known = ", ".join(str(c) for c in _ARTIFACT_CLASS_TO_TARGET_TYPE)
            msg = f"Cannot resolve VerifyTargetType for artifact_class={target.artifact_class!r}. Known classes: {known}"
            raise VerifyTargetUnknownError(msg)

        return VerifyTarget(
            artifact_ref_record_key=target.record_key,
            target_type=target_type,
        )

    def _layer_for_kind(self, kind: QALayerKind) -> QALayer:
        """Return the layer instance for Layer 1 or Layer 3.

        Args:
            kind: Layer identifier (STRUCTURAL or ADVERSARIAL only;
                LLM_EVALUATOR handled separately via ``_layer2_pairs``).

        Returns:
            The matching ``QALayer`` instance held by this facade.
        """
        if kind is QALayerKind.STRUCTURAL:
            return self.layer_1
        if kind is QALayerKind.ADVERSARIAL:
            return self.layer_3
        msg = f"No single-layer instance for kind {kind!r}"  # pragma: no cover
        raise ValueError(msg)  # pragma: no cover

    def _execute_layer(
        self,
        layer: QALayer,
        ctx: VerifyContextBundle,
        story_id: str,
        kind: QALayerKind,
        *,
        review_input: object | None = None,
        story_context: object | None = None,
    ) -> LayerResult:
        """Execute a single layer, wrapping exceptions as BLOCKING findings.

        Args:
            layer: The QALayer instance to execute.
            ctx: Context bundle (provides story_dir).
            story_id: Story display-ID (for error messages).
            kind: Layer kind identifier (for error messages).
            review_input: Optional ``Layer2ReviewInput`` passed to Layer-2
                reviewers. Layer 1/3 ignore it.
            story_context: Optional pre-resolved ``StoryContext`` injected by
                the caller (AG3-035: eliminates direct state_backend import
                inside verify_system). When ``None``, falls back to the
                IMPLEMENTATION stub (safe default for tests without a DB).

        Returns:
            ``LayerResult`` -- either the genuine result or a synthetic
            BLOCKING result if the layer raised an unexpected exception.
        """
        from agentkit.story_context_manager.models import StoryContext
        from agentkit.story_context_manager.types import StoryMode, StoryType
        from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput as _L2Input

        effective_ri = review_input if isinstance(review_input, _L2Input) else None

        try:
            # AG3-035: StoryContext wird via Injection uebergeben
            # (story_context-Parameter), nicht via direktem state_backend.store-Import.
            # Der Aufrufer (run_qa_subflow) laedt den StoryContext einmalig und
            # reicht ihn hier ein (BC-Topologie-konform).
            # Fallback auf IMPLEMENTATION-Stub wenn kein StoryContext verfuegbar
            # (Testpfad ohne persistierten Kontext, FK-27 §27.4).
            if story_context is not None and isinstance(story_context, StoryContext):
                layer_ctx = story_context
            else:
                layer_ctx = StoryContext(
                    project_key="verify-system-run",
                    story_id=story_id,
                    story_type=StoryType.IMPLEMENTATION,
                    execution_route=StoryMode.EXECUTION,
                )
            return layer.evaluate(layer_ctx, ctx.story_dir, review_input=effective_ri)
        except Exception as exc:
            error_msg = f"Layer {kind!r} raised an unexpected exception: {type(exc).__name__}: {exc}"
            logger.error(error_msg, exc_info=exc)
            wrapped = LayerExecutionError(error_msg)
            wrapped.__cause__ = exc
            blocking_finding = Finding(
                layer=kind.value,
                check="layer_execution",
                severity=Severity.BLOCKING,
                message=error_msg,
                trust_class=TrustClass.SYSTEM,
            )
            return LayerResult(
                layer=kind.value,
                passed=False,
                findings=(blocking_finding,),
                metadata={"layer_execution_error": str(wrapped)},
            )

    def _write_layer_envelope(
        self,
        *,
        spec: _LayerArtifactSpec,
        result: LayerResult,
        ctx: VerifyContextBundle,
        story_id: str,
        now_str: str,
        qa_cycle_fields: dict[str, object],
    ) -> None:
        """Schreibt ein einzelnes Layer-Envelope via ArtifactManager.

        AG3-026 §AK7: pro Layer-Artefakt-Spec eine eigene
        ``ArtifactEnvelope`` mit dem zugehoerigen Producer + Stage.
        W1: Layer-2 Envelopes tragen jetzt eigenstaendige LayerResult-
        Payloads pro Reviewer (kein synthetic Payload-Repeat mehr).

        AG3-026 §AK8: QA-Zyklus-Felder (``qa_cycle_id``,
        ``qa_cycle_round``, ``evidence_epoch``, ``evidence_fingerprint``)
        werden aus ``ctx.phase_envelope`` (jetzt ``PhaseEnvelopeView``)
        in jede Envelope-Payload eingebettet, sofern dort gesetzt.
        """
        payload = _qa.serialize_layer_result_payload(result, ctx.attempt)
        payload.update(qa_cycle_fields)
        envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id=story_id,
            run_id=ctx.run_id,
            stage=spec.stage,
            attempt=ctx.attempt,
            producer=Producer(
                type=spec.producer_type,
                name=spec.producer_name,
                id=ProducerId(
                    f"{spec.producer_name}-{ctx.run_id}-{ctx.attempt}"
                ),
            ),
            started_at=datetime.fromisoformat(now_str),
            finished_at=datetime.fromisoformat(now_str),
            status=EnvelopeStatus.PASS if result.passed else EnvelopeStatus.FAIL,
            artifact_class=ArtifactClass.QA,
            payload=payload,
        )
        self.artifact_manager.write(envelope)

    def _write_policy_artifact(
        self,
        *,
        decision: VerifyDecision,
        ctx: VerifyContextBundle,
        story_id: str,
        now_str: str,
        qa_cycle_fields: dict[str, object],
    ) -> str:
        """Schreibt das Policy-Decision-Envelope (``decision.json``).

        AG3-026 §AK7: Filename ist ``decision.json`` (kanonisch nach FK-27 §27.7;
        Stage ``qa-policy-decision``; nicht die alte Dash-Form ``verify-decision.json``
        / ``qa-verify-decision``).
        QA-Zyklus-Felder werden analog Layer-Artefakten eingebettet.

        Returns:
            ``"decision.json"`` (FK-27 §27.7 / AG3-026 §AK7).
        """
        from agentkit.verify_system.policy_engine.projections import (
            build_verify_decision_artifact,
        )

        payload = build_verify_decision_artifact(decision, attempt_nr=ctx.attempt)
        payload.update(qa_cycle_fields)
        envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id=story_id,
            run_id=ctx.run_id,
            stage=_POLICY_ARTIFACT_SPEC.stage,
            attempt=ctx.attempt,
            producer=Producer(
                type=_POLICY_ARTIFACT_SPEC.producer_type,
                name=_POLICY_ARTIFACT_SPEC.producer_name,
                id=ProducerId(
                    f"{_POLICY_ARTIFACT_SPEC.producer_name}-{ctx.run_id}-{ctx.attempt}"
                ),
            ),
            started_at=datetime.fromisoformat(now_str),
            finished_at=datetime.fromisoformat(now_str),
            status=EnvelopeStatus.PASS if decision.passed else EnvelopeStatus.FAIL,
            artifact_class=ArtifactClass.QA,
            payload=payload,
        )
        self.artifact_manager.write(envelope)
        return _POLICY_ARTIFACT_SPEC.filename

    # ------------------------------------------------------------------
    # Private static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _kind_to_single_artifacts(
        kind: QALayerKind,
    ) -> tuple[_LayerArtifactSpec, ...]:
        """Return the single-artefact specs for Layer 1 or Layer 3.

        Layer 2 is handled separately via ``_layer2_pairs``.

        Args:
            kind: Layer kind (STRUCTURAL or ADVERSARIAL).

        Returns:
            Tuple with one ``_LayerArtifactSpec``.
        """
        if kind is QALayerKind.STRUCTURAL:
            return _LAYER_1_ARTIFACTS
        if kind is QALayerKind.ADVERSARIAL:
            return _LAYER_3_ARTIFACTS
        msg = f"_kind_to_single_artifacts called with non-single kind {kind!r}"
        raise ValueError(msg)  # pragma: no cover

