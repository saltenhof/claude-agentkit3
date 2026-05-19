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
from agentkit.core_types.qa_artifact_names import (
    LAYER_ARTIFACT_FILES,
    VERIFY_DECISION_FILE,
)
from agentkit.verify_system.adversarial_orchestrator.challenger import (
    AdversarialChallenger,
)
from agentkit.verify_system.contract import (
    VerifyContextBundle,
    VerifyTarget,
    VerifyTargetType,
    _QaSubflowExecutionResult,
)
from agentkit.verify_system.errors import LayerExecutionError, VerifyTargetUnknownError
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

#: Maps layer kind -> (stage-id, producer-name, producer-type)
_LAYER_META: dict[QALayerKind, tuple[str, str, ProducerType]] = {
    QALayerKind.STRUCTURAL: (
        "qa-layer-structural",
        "verify-system.layer-1-structural",
        ProducerType.DETERMINISTIC,
    ),
    QALayerKind.LLM_EVALUATOR: (
        "qa-layer-semantic",
        "verify-system.layer-2-llm",
        ProducerType.LLM_REVIEWER,
    ),
    QALayerKind.ADVERSARIAL: (
        "qa-layer-adversarial",
        "verify-system.layer-3-adversarial",
        ProducerType.LLM_REVIEWER,
    ),
}

#: Policy/decision artefact meta
_POLICY_STAGE = "qa-verify-decision"
_POLICY_PRODUCER_NAME = "verify-system.layer-4-policy"
_POLICY_PRODUCER_TYPE = ProducerType.DETERMINISTIC

#: Maps layer kind -> FK-27 §27.7 filename (for non-policy layers)
_KIND_TO_FILENAME: dict[QALayerKind, str] = {
    QALayerKind.STRUCTURAL: LAYER_ARTIFACT_FILES["structural"],
    QALayerKind.LLM_EVALUATOR: LAYER_ARTIFACT_FILES["semantic"],
    QALayerKind.ADVERSARIAL: LAYER_ARTIFACT_FILES["adversarial"],
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
        max_major_findings: int = 0,
        artifact_manager: ArtifactManager | None = None,
    ) -> VerifySystem:
        """Construct a ``VerifySystem`` with default sub-components.

        Builds all five sub-components with sensible defaults. When
        ``artifact_manager`` is ``None``, a no-op stub manager is used;
        callers that need real persistence must supply one explicitly.

        Args:
            max_major_findings: Threshold for the policy engine. Mirrors
                :class:`PolicyEngine` -- MAJOR findings beyond this count
                turn into blocking findings (FK-27 §27.4.2 / §27.7.2).
            artifact_manager: Optional ``ArtifactManager`` for artefact
                writes. Defaults to a stub that satisfies the interface.

        Returns:
            A frozen ``VerifySystem`` with default-configured
            sub-components.
        """
        if artifact_manager is None:
            artifact_manager = _NoOpArtifactManager()
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

        for kind in layer_kinds:
            if kind is QALayerKind.POLICY:
                # Policy runs after all data layers; handled in step 5/6.
                continue

            layer_instance = self._layer_for_kind(kind)
            result = self._execute_layer(layer_instance, ctx, story_id, kind)
            layer_results.append(result)

            # Write QA artefact for this layer.
            artifact_ref = self._write_layer_artifact(
                kind=kind,
                result=result,
                ctx=ctx,
                story_id=story_id,
                now_str=now_str,
            )
            artifact_refs_written.append(artifact_ref)

        # Step 5: Policy decision.
        decision = self.policy_engine.decide(layer_results)

        # Step 6: Write policy decision artefact.
        decision_ref = self._write_policy_artifact(
            decision=decision,
            ctx=ctx,
            story_id=story_id,
            now_str=now_str,
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

    def _write_layer_artifact(
        self,
        *,
        kind: QALayerKind,
        result: LayerResult,
        ctx: VerifyContextBundle,
        story_id: str,
        now_str: str,
    ) -> str:
        """Write a QA artefact envelope for a data layer via ArtifactManager.

        Args:
            kind: The layer kind (determines producer + filename).
            result: The layer's evaluation result.
            ctx: Context bundle (run_id, attempt, phase_envelope).
            story_id: Story display-ID.
            now_str: ISO-8601 UTC timestamp string for envelope timestamps.

        Returns:
            The canonical FK-27 §27.7 filename for the written artefact.
        """
        stage, producer_name, producer_type = _LAYER_META[kind]
        envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id=story_id,
            run_id=ctx.run_id,
            stage=stage,
            attempt=ctx.attempt,
            producer=Producer(
                type=producer_type,
                name=producer_name,
                id=ProducerId(f"{producer_name}-{ctx.run_id}-{ctx.attempt}"),
            ),
            started_at=datetime.fromisoformat(now_str),
            finished_at=datetime.fromisoformat(now_str),
            status=EnvelopeStatus.PASS if result.passed else EnvelopeStatus.FAIL,
            artifact_class=ArtifactClass.QA,
            payload=_layer_result_to_payload(result, attempt=ctx.attempt),
        )
        self.artifact_manager.write(envelope)
        return _KIND_TO_FILENAME[kind]

    def _write_policy_artifact(
        self,
        *,
        decision: VerifyDecision,
        ctx: VerifyContextBundle,
        story_id: str,
        now_str: str,
    ) -> str:
        """Write the policy decision artefact via ArtifactManager.

        Args:
            decision: Aggregated policy decision.
            ctx: Context bundle (run_id, attempt).
            story_id: Story display-ID.
            now_str: ISO-8601 UTC timestamp string.

        Returns:
            The canonical FK-27 §27.7 filename for the decision artefact.
        """
        from agentkit.verify_system.policy_engine.projections import (
            build_verify_decision_artifact,
        )

        envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id=story_id,
            run_id=ctx.run_id,
            stage=_POLICY_STAGE,
            attempt=ctx.attempt,
            producer=Producer(
                type=_POLICY_PRODUCER_TYPE,
                name=_POLICY_PRODUCER_NAME,
                id=ProducerId(
                    f"{_POLICY_PRODUCER_NAME}-{ctx.run_id}-{ctx.attempt}"
                ),
            ),
            started_at=datetime.fromisoformat(now_str),
            finished_at=datetime.fromisoformat(now_str),
            status=EnvelopeStatus.PASS if decision.passed else EnvelopeStatus.FAIL,
            artifact_class=ArtifactClass.QA,
            payload=build_verify_decision_artifact(decision, attempt_nr=ctx.attempt),
        )
        self.artifact_manager.write(envelope)
        return VERIFY_DECISION_FILE


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


# ---------------------------------------------------------------------------
# No-op stub ArtifactManager for create_default() when no real manager given
# ---------------------------------------------------------------------------


class _NoOpArtifactManager(ArtifactManager):
    """Stub ArtifactManager that silently discards all writes.

    Used by ``VerifySystem.create_default()`` when no real manager is
    supplied. This keeps the default factory zero-dependency so that
    callers that only use ``policy_decision()`` or ``adversarial_layer()``
    (AG3-023/AG3-024 patterns) do not need a full storage setup.

    ``read`` and ``read_latest`` are intentionally not overridden -- they
    will raise ``ArtifactNotFoundError`` from the base class, which is
    the correct fail-closed behaviour.
    """

    def __init__(self) -> None:
        # Deliberately do NOT call super().__init__() -- we bypass
        # the repository/validator requirement for this stub.
        pass

    def write(self, envelope: ArtifactEnvelope) -> ArtifactReference:
        """Silently discard the envelope; return a synthetic reference.

        Args:
            envelope: The envelope to (not) persist.

        Returns:
            A synthetic ``ArtifactReference`` with the envelope's fields.
        """
        from agentkit.artifacts import ArtifactReference

        return ArtifactReference(
            artifact_class=envelope.artifact_class,
            story_id=envelope.story_id,
            run_id=envelope.run_id,
            record_key=f"noop/{envelope.stage}/{envelope.attempt}",
        )
