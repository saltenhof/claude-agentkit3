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
    ) -> PolicyVerdict

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
    ProducerType,
)
from agentkit.core_types import ArtifactClass, PolicyVerdict, QaContext
from agentkit.core_types.qa_artifact_names import LAYER_ARTIFACT_FILES
from agentkit.verify_system.adversarial_orchestrator.challenger import (
    AdversarialChallenger,
)
from agentkit.verify_system.contract import (
    VerifyContextBundle,
    VerifyTarget,
    VerifyTargetType,
    _QaSubflowExecutionResult,
)
from agentkit.verify_system.errors import (
    LayerExecutionError,
    VerifySystemError,
    VerifyTargetUnknownError,
)
from agentkit.verify_system.llm_evaluator.reviewer import SemanticReviewer
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

# ---------------------------------------------------------------------------
# Layer-name -> FK-27 §27.7 artefact filename + producer registry entry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _LayerArtifactSpec:
    """One QA artefact write specification (FK-27 §27.7 + AG3-026 §AK7)."""

    filename: str
    stage: str
    producer_name: str
    producer_type: ProducerType


#: Layer 1 -- single artefact ``structural.json`` (FK-27 §27.7)
_LAYER_1_ARTIFACTS: tuple[_LayerArtifactSpec, ...] = (
    _LayerArtifactSpec(
        filename=LAYER_ARTIFACT_FILES["structural"],
        stage="qa-layer-structural",
        producer_name="verify-system.layer-1-structural",
        producer_type=ProducerType.DETERMINISTIC,
    ),
)

#: Layer 2 -- three artefacts (AG3-026 §AK7): qa_review.json,
#: semantic_review.json, doc_fidelity.json. Filenames mit Unterstrich
#: gemaess Story-Wortlaut (vgl. FK-27 §27.7).
_LAYER_2_ARTIFACTS: tuple[_LayerArtifactSpec, ...] = (
    _LayerArtifactSpec(
        filename="qa_review.json",
        stage="qa-layer-qa-review",
        producer_name="verify-system.layer-2-qa-review",
        producer_type=ProducerType.LLM_REVIEWER,
    ),
    _LayerArtifactSpec(
        filename="semantic_review.json",
        stage="qa-layer-semantic-review",
        producer_name="verify-system.layer-2-semantic-review",
        producer_type=ProducerType.LLM_REVIEWER,
    ),
    _LayerArtifactSpec(
        filename="doc_fidelity.json",
        stage="qa-layer-doc-fidelity",
        producer_name="verify-system.layer-2-doc-fidelity",
        producer_type=ProducerType.LLM_REVIEWER,
    ),
)

#: Layer 3 -- single artefact ``adversarial.json``
_LAYER_3_ARTIFACTS: tuple[_LayerArtifactSpec, ...] = (
    _LayerArtifactSpec(
        filename=LAYER_ARTIFACT_FILES["adversarial"],
        stage="qa-layer-adversarial",
        producer_name="verify-system.layer-3-adversarial",
        producer_type=ProducerType.LLM_REVIEWER,
    ),
)

#: Policy/decision artefact (AG3-026 §AK7: ``decision.json``,
#: nicht ``verify-decision.json`` -- Letzteres ist AG3-023-Bestand fuer
#: write_verify_decision_artifacts und bleibt dort unangetastet).
_POLICY_ARTIFACT_SPEC = _LayerArtifactSpec(
    filename="decision.json",
    stage="qa-policy-decision",
    producer_name="verify-system.layer-4-policy",
    producer_type=ProducerType.DETERMINISTIC,
)

#: Maps layer kind -> tuple of artefact specs (1, 3, 1).
_KIND_TO_ARTIFACTS: dict[QALayerKind, tuple[_LayerArtifactSpec, ...]] = {
    QALayerKind.STRUCTURAL: _LAYER_1_ARTIFACTS,
    QALayerKind.LLM_EVALUATOR: _LAYER_2_ARTIFACTS,
    QALayerKind.ADVERSARIAL: _LAYER_3_ARTIFACTS,
}

#: Maps artifact_class to internal VerifyTargetType.
#: Only classes that represent reviewable artefacts are valid.
#: All others -> VerifyTargetUnknownError (fail-closed, AG3-026 §2.1.4).
_ARTIFACT_CLASS_TO_TARGET_TYPE: dict[ArtifactClass, VerifyTargetType] = {
    ArtifactClass.WORKER: VerifyTargetType.IMPLEMENTATION,
    ArtifactClass.QA: VerifyTargetType.IMPLEMENTATION,
    ArtifactClass.ENTWURF: VerifyTargetType.EXPLORATION,
    ArtifactClass.HANDOVER: VerifyTargetType.IMPLEMENTATION,
    ArtifactClass.ADVERSARIAL_TEST_SANDBOX: VerifyTargetType.IMPLEMENTATION,
}


@dataclass(frozen=True)
class VerifySystem:
    """Top-Surface of the verify-system Capability-BC.

    Holds the sub-components that the BC composes internally. Cross-BC
    consumers obtain instances through :meth:`create_default` and call
    the published methods of this class. The sub-component fields are
    intentionally typed against the internal classes; consumers must
    not reach into them.

    Attributes:
        layer_1: Layer-1 deterministic structural checker.
            Must satisfy :class:`QALayer` protocol.
        layer_2: Layer-2 LLM-based evaluator runner.
            Must satisfy :class:`QALayer` protocol.
        layer_3: Layer-3 adversarial orchestrator.
            Must satisfy :class:`QALayer` protocol.
        policy_engine: Layer-4 deterministic aggregator
            (``agentkit.verify_system.policy_engine``).
        artifact_manager: ArtifactManager for writing QA artefacts.
        adversarial_challenger: Backward-compatible alias for ``layer_3``;
            kept to avoid breaking AG3-023/AG3-024 consumers.
    """

    layer_1: QALayer
    layer_2: QALayer
    layer_3: QALayer
    policy_engine: PolicyEngine
    artifact_manager: ArtifactManager

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

        Builds all five sub-components with sensible defaults.
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
            layer_2=SemanticReviewer(),
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
    ) -> PolicyVerdict:
        """Execute the full QA-subflow and return a PASS/FAIL verdict.

        Steps:
        1. Resolve ``target`` to an internal ``VerifyTarget`` (fail-closed
           on unknown target_type).
        2. Select layers via ``select_layers(qa_context)``.
        3. Execute each selected layer in order; wrap unexpected exceptions
           in ``LayerExecutionError`` and aggregate as BLOCKING findings.
        4. Write a QA artefact via ``ArtifactManager`` for each executed layer.
        5. Run the policy engine over all collected ``LayerResult`` instances.
        6. Write the policy decision artefact.
        7. Return ``PolicyVerdict.PASS`` or ``PolicyVerdict.FAIL``.

        Args:
            ctx: Run-time context bundle (run_id, story_dir, phase_envelope,
                attempt).
            story_id: Story display-ID (e.g. ``AG3-042``).
            qa_context: Invocation context that controls layer selection.
            target: Typed reference to the artefact under review.

        Returns:
            ``PolicyVerdict.PASS`` if the policy engine is satisfied;
            ``PolicyVerdict.FAIL`` otherwise.

        Raises:
            VerifyTargetUnknownError: If the target's artifact_class
                cannot be mapped to a ``VerifyTargetType``.
        """
        # Step 1: Resolve target (fail-closed on unknown type).
        verify_target = self._resolve_verify_target(ctx, target)

        # Step 2: Select layers.
        layer_kinds = select_layers(qa_context)

        # Step 3 + 4: Execute layers in order and write artefacts.
        layer_results: list[LayerResult] = []
        artifact_refs_written: list[str] = []
        now_str = _utc_now_iso()

        qa_cycle_fields = _extract_qa_cycle_fields(ctx)

        for kind in layer_kinds:
            if kind is QALayerKind.POLICY:
                # Policy runs after all data layers; handled in step 5/6.
                continue

            layer_instance = self._layer_for_kind(kind)
            result = self._execute_layer(layer_instance, ctx, story_id, kind)
            layer_results.append(result)

            # Write QA artefact(s) for this layer. AG3-026 §AK7: Layer 2
            # produces three artefacts (qa_review/semantic_review/
            # doc_fidelity); Layer 1 and 3 produce one each.
            for spec in _KIND_TO_ARTIFACTS[kind]:
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

        # Build internal result detail (not returned to callers).
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

        # Step 7: Return exactly PolicyVerdict (AK11 / §2.1.3).
        return decision.verdict

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_verify_target(
        self,
        ctx: VerifyContextBundle,
        target: ArtifactReference,
    ) -> VerifyTarget:
        """Map ``ArtifactReference`` to an internal ``VerifyTarget``.

        Args:
            ctx: Context bundle (used for future path-scope derivation).
            target: Public artefact reference.

        Returns:
            An internal ``VerifyTarget`` with a resolved ``VerifyTargetType``.

        Raises:
            VerifyTargetUnknownError: If the artifact_class has no known
                mapping to ``VerifyTargetType``.
        """
        target_type = _ARTIFACT_CLASS_TO_TARGET_TYPE.get(target.artifact_class)
        if target_type is None:
            msg = (
                f"Cannot resolve VerifyTargetType for "
                f"artifact_class={target.artifact_class!r}. "
                "Known classes: "
                + ", ".join(str(c) for c in _ARTIFACT_CLASS_TO_TARGET_TYPE)
            )
            raise VerifyTargetUnknownError(msg)

        return VerifyTarget(
            artifact_ref_record_key=target.record_key,
            target_type=target_type,
        )

    def _layer_for_kind(self, kind: QALayerKind) -> QALayer:
        """Return the layer instance corresponding to a ``QALayerKind``.

        Args:
            kind: Layer identifier.

        Returns:
            The matching ``QALayer`` instance held by this facade.
        """
        if kind is QALayerKind.STRUCTURAL:
            return self.layer_1
        if kind is QALayerKind.LLM_EVALUATOR:
            return self.layer_2
        if kind is QALayerKind.ADVERSARIAL:
            return self.layer_3
        msg = f"No layer instance for kind {kind!r}"  # pragma: no cover
        raise ValueError(msg)  # pragma: no cover

    def _execute_layer(
        self,
        layer: QALayer,
        ctx: VerifyContextBundle,
        story_id: str,
        kind: QALayerKind,
    ) -> LayerResult:
        """Execute a single layer, wrapping exceptions as BLOCKING findings.

        Args:
            layer: The QALayer instance to execute.
            ctx: Context bundle (provides story_dir).
            story_id: Story display-ID (for error messages).
            kind: Layer kind identifier (for error messages).

        Returns:
            ``LayerResult`` -- either the genuine result or a synthetic
            BLOCKING result if the layer raised an unexpected exception.
        """
        from agentkit.story_context_manager.models import StoryContext
        from agentkit.story_context_manager.types import StoryMode, StoryType

        try:
            # Build a minimal StoryContext from the bundle for layer.evaluate().
            # Layer implementations receive story_dir from ctx.story_dir.
            stub_ctx = StoryContext(
                project_key="verify-system-run",
                story_id=story_id,
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
            )
            return layer.evaluate(stub_ctx, ctx.story_dir)
        except Exception as exc:
            error_msg = (
                f"Layer {kind!r} raised an unexpected exception: "
                f"{type(exc).__name__}: {exc}"
            )
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
        Layer 2 ruft diese Methode 3-fach (qa_review, semantic_review,
        doc_fidelity) -- die LayerResult-Payload wird in alle drei
        Envelopes geschrieben, da die Story Layer 2 als eine logische
        Pruefebene mit drei FK-27-Artefakten beschreibt.

        AG3-026 §AK8: QA-Zyklus-Felder (``qa_cycle_id``,
        ``qa_cycle_round``, ``evidence_epoch``, ``evidence_fingerprint``)
        werden aus ``ctx.phase_envelope`` in jede Envelope-Payload
        eingebettet, sofern dort gesetzt.
        """
        payload = _layer_result_to_payload(result, attempt=ctx.attempt)
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

        AG3-026 §AK7: Filename ist ``decision.json`` (nicht
        ``verify-decision.json``; Letzteres ist AG3-023-Bestand fuer
        ``write_verify_decision_artifacts`` und bleibt dort unangetastet).
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


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    from agentkit.boundary.shared.time import now_iso

    return now_iso()


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


def _extract_qa_cycle_fields(ctx: VerifyContextBundle) -> dict[str, object]:
    """Extract QA-Zyklus-Identitaeten from the phase envelope payload.

    AG3-026 §AK8 + FK-27 §27.2.1: wenn ``ctx.phase_envelope`` einen
    ``ImplementationPayload`` traegt, werden ``qa_cycle_id``,
    ``qa_cycle_round``, ``evidence_epoch``, ``evidence_fingerprint`` in
    jede erzeugte QA-Artefakt-Payload geschrieben. Felder, die im
    PhaseState ``None``/Default sind, werden nicht ausgegeben (sauberes
    JSON, keine ``null``-Stuempfe).

    Befuellung/Invalidierung dieser Felder ist AG3-041 (THEME-009).
    """
    envelope = ctx.phase_envelope
    if envelope is None:
        return {}
    state = getattr(envelope, "state", None)
    payload = getattr(state, "payload", None) if state is not None else None
    if payload is None:
        return {}
    fields: dict[str, object] = {}
    for attr in (
        "qa_cycle_id",
        "qa_cycle_round",
        "evidence_epoch",
        "evidence_fingerprint",
    ):
        value = getattr(payload, attr, None)
        if value is None:
            continue
        # datetimes serialise to ISO-8601 strings for JSON payload portability.
        if hasattr(value, "isoformat"):
            fields[attr] = value.isoformat()
        else:
            fields[attr] = value
    return fields
