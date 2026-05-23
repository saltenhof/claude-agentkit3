"""Top-Surface of the verify-system Bounded Context.

``VerifySystem`` is the Capability-A-Top-Komponente of the BC
``verify-system`` (FK-07 §7.4.2, FK-27, ``concept/_meta/bc-cut-decisions.md``
§"BC 2: verify-system"). Cross-BC callers (e.g. ``agentkit.implementation``)
MUST go through this facade and MUST NOT import sub-components such as
``policy_engine.PolicyEngine`` or ``adversarial_orchestrator.challenger.
AdversarialChallenger`` directly (Sichtbarkeitsregel, AC001).

Normative contract (BC-Cut + FK-27 + formal.verify.commands):

    VerifySystem.run_qa_subflow(
        ctx, story_id, qa_context, target
    ) -> QaSubflowOutcome  # AG3-026 Pass-2 Befund A: was PolicyVerdict

Quelle:
  - AG3-026 §2.1.1 -- VerifySystem-Top-Klasse
  - ``concept/_meta/bc-cut-decisions.md §BC 2 verify-system``
  - ``concept/_meta/bc-cut-decisions.md §QA-Subflow-Vertrag``
  - FK-27 §27.3 (QA-Subflow-Top)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from agentkit.artifacts import (
    ArtifactEnvelope,
    ArtifactManager,
    ArtifactReference,
    EnvelopeStatus,
    Producer,
    ProducerId,
)
from agentkit.core_types import ArtifactClass, QaContext
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
    _LayerArtifactSpec,
)
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
    Severity,
    TrustClass,
)
from agentkit.verify_system.routing import QALayerKind, select_layers
from agentkit.verify_system.structural.checker import StructuralChecker

logger = logging.getLogger(__name__)


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
        adversarial_challenger: Backward-compatible alias for ``layer_3``;
            kept to avoid breaking AG3-023/AG3-024 consumers.
    """

    layer_1: QALayer
    layer_2a: QALayer
    layer_2b: QALayer
    layer_2c: QALayer
    layer_3: QALayer
    policy_engine: PolicyEngine
    artifact_manager: ArtifactManager

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
        return cls(
            layer_1=StructuralChecker(),
            layer_2a=QaReviewReviewer(),
            layer_2b=SemanticReviewer(),
            layer_2c=DocFidelityReviewer(),
            layer_3=AdversarialChallenger(),
            policy_engine=PolicyEngine(max_major_findings=max_major_findings),
            artifact_manager=artifact_manager,
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

        # Step 2: Select layers.
        layer_kinds = select_layers(qa_context)

        # Step 3 + 4: Execute layers in order and write artefacts.
        layer_results: list[LayerResult] = []
        artifact_refs_written: list[str] = []
        now_str = self._utc_now_iso()

        qa_cycle_fields = self._extract_qa_cycle_fields(ctx)

        for kind in layer_kinds:
            if kind is QALayerKind.POLICY:
                # Policy runs after all data layers; handled in step 5/6.
                continue

            if kind is QALayerKind.LLM_EVALUATOR:
                # W1: Layer 2 runs three distinct reviewers, each producing
                # its own LayerResult and its own envelope.
                for layer_instance, spec in self._layer2_pairs():
                    result = self._execute_layer(
                        layer_instance, ctx, story_id, kind,
                        review_input=effective_review_input,
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
            else:
                layer_instance = self._layer_for_kind(kind)
                result = self._execute_layer(
                    layer_instance, ctx, story_id, kind,
                    review_input=effective_review_input,
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

        # Step 5: Policy decision.
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
        from agentkit.verify_system.remediation.feedback import build_feedback

        feedback = build_feedback(decision, story_id, ctx.attempt)

        # Step 8: Return QaSubflowOutcome (public DTO, AK11 / §2.1.3).
        return QaSubflowOutcome(
            verdict=decision.verdict,
            decision=decision,
            artifact_refs=tuple(artifact_refs_written),
            attempt_nr=ctx.attempt,
            qa_cycle_round=ctx.attempt,
            feedback=feedback,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
    ) -> LayerResult:
        """Execute a single layer, wrapping exceptions as BLOCKING findings.

        Args:
            layer: The QALayer instance to execute.
            ctx: Context bundle (provides story_dir).
            story_id: Story display-ID (for error messages).
            kind: Layer kind identifier (for error messages).
            review_input: Optional ``Layer2ReviewInput`` passed to Layer-2
                reviewers. Layer 1/3 ignore it.

        Returns:
            ``LayerResult`` -- either the genuine result or a synthetic
            BLOCKING result if the layer raised an unexpected exception.
        """
        from agentkit.state_backend.store import load_story_context  # DRIFT-AG3-035
        from agentkit.story_context_manager.models import StoryContext
        from agentkit.story_context_manager.types import StoryMode, StoryType
        from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput as _L2Input

        effective_ri = review_input if isinstance(review_input, _L2Input) else None

        try:
            # DRIFT-AG3-035: verify_system reads StoryContext via state_backend
            # until ProjectionAccessor lands (AG3-035). Structural resolution
            # deferred; BC-Topology documented in _bearbeitungsreihenfolge.md §2a.
            # Load the real StoryContext from story_dir so that
            # story_type-specific checks (e.g. StructuralChecker phase-snapshot
            # validation) use the correct phase profile (FK-27 §27.4 / AG3-026
            # Pass-2 fix).  Fall back to a minimal IMPLEMENTATION stub only when
            # the story_dir has no persisted context yet.
            layer_ctx = load_story_context(ctx.story_dir) or StoryContext(
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
        payload = self._layer_result_to_payload(result, attempt=ctx.attempt)
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

    @staticmethod
    def _utc_now_iso() -> str:
        """Return the current UTC time as an ISO-8601 string."""
        from agentkit.boundary.shared.time import now_iso

        return now_iso()

    @staticmethod
    def _layer_result_to_payload(
        result: LayerResult,
        attempt: int,
    ) -> dict[str, object]:
        """Serialise a ``LayerResult`` to a JSON-compatible dict payload.

        Args:
            result: The layer evaluation result to serialise.
            attempt: QA-subflow attempt counter.

        Returns:
            Dict suitable for use as ``ArtifactEnvelope.payload``.
        """
        from agentkit.verify_system.policy_engine.projections import serialize_layer_result

        return serialize_layer_result(result, attempt_nr=attempt)

    @staticmethod
    def _extract_qa_cycle_fields(ctx: VerifyContextBundle) -> dict[str, object]:
        """Extract QA-Zyklus-Identitaeten from the PhaseEnvelopeView.

        AG3-026 §AK8 + FK-27 §27.2.1: wenn ``ctx.phase_envelope`` ein
        ``PhaseEnvelopeView`` traegt, werden ``qa_cycle_id``,
        ``qa_cycle_round``, ``evidence_epoch``, ``evidence_fingerprint`` in
        jede erzeugte QA-Artefakt-Payload geschrieben. Felder, die ``None``
        sind, werden nicht ausgegeben (sauberes JSON, keine ``null``-Stuempfe).

        W2: ``ctx.phase_envelope`` ist jetzt ``PhaseEnvelopeView | None`` statt
        ``PhaseEnvelope | None``; kein ``pipeline_engine``-Import mehr noetig.

        Befuellung/Invalidierung dieser Felder ist AG3-041 (THEME-009).
        """
        view = ctx.phase_envelope
        if view is None:
            return {}
        fields: dict[str, object] = {}
        for attr in (
            "qa_cycle_id",
            "qa_cycle_round",
            "evidence_epoch",
            "evidence_fingerprint",
        ):
            value = getattr(view, attr, None)
            if value is None:
                continue
            # datetimes serialise to ISO-8601 strings for JSON payload portability.
            if hasattr(value, "isoformat"):
                fields[attr] = value.isoformat()
            else:
                fields[attr] = value
        return fields
