"""Top surface of the verify-system bounded context."""

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
from agentkit.core_types import ArtifactClass, PolicyVerdict, QaContext, SpawnRequest
from agentkit.verify_system import _artifact_specs
from agentkit.verify_system.adversarial_orchestrator.challenger import (
    AdversarialChallenger,
)
from agentkit.verify_system.adversarial_orchestrator.spawn import AdversarialSpawner
from agentkit.verify_system.contract import (
    QaSubflowOutcome,
    VerifyContextBundle,
    VerifyTarget,
    _QaSubflowExecutionResult,
)
from agentkit.verify_system.defaults import (
    VerifySystemDefaultOptions,
    resolve_default_options,
)
from agentkit.verify_system.errors import (
    LayerExecutionError,
    VerifySystemError,
    VerifyTargetUnknownError,
)
from agentkit.verify_system.implementation_evidence_gate import (
    evaluate_implementation_evidence_gate,
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
from agentkit.verify_system.review_completion import (
    NullReviewCompletionSink,
    ReviewCompletionEvent,
    ReviewCompletionSink,
)
from agentkit.verify_system.routing import QALayerKind, select_layers
from agentkit.verify_system.sonarqube_gate.port import (
    ABSENT_SONAR_GATE_PORT,
    SonarGateInputPort,
)
from agentkit.verify_system.sonarqube_gate.stage_runner import (
    SonarStageResult,
    run_sonarqube_gate_stage,
)
from agentkit.verify_system.stage_registry.registry import StageRegistry
from agentkit.verify_system.stage_registry.stages import StageKind
from agentkit.verify_system.structural.system_evidence import (
    ABSENT_CHANGE_EVIDENCE_PORT,
    ChangeEvidencePort,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.config.models import ConformanceConfig
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.types import StoryType
    from agentkit.telemetry.emitters import EventEmitter
    from agentkit.verify_system.conformance_service import FidelityContext
    from agentkit.verify_system.llm_evaluator import Layer2ReviewInput, LlmClient, ParallelEvalRunner
    from agentkit.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluatorResult,
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

#: Default Layer-2 review-completion sink (FK-27 §27.4.3 / §27.5.5): a No-op that
#: drops ``llm_call_complete`` emissions on the test path. NOT a guard weakening:
#: ``guard.multi_llm`` counts canonical events, so a dropped emission leaves the
#: per-role count at 0 -> BLOCKING FAIL (fail-closed). The productive
#: telemetry-emitting adapter is wired via ``composition_root.build_verify_system``.
_NULL_REVIEW_COMPLETION_SINK: ReviewCompletionSink = NullReviewCompletionSink()


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
    layer2_runner: ParallelEvalRunner | None = None
    layer2_llm_client: LlmClient | None = None
    conformance_emitter: EventEmitter | None = None
    #: FK-32 §32.4b.3 prompt-size thresholds for the ConformanceService. ``None``
    #: => the service's built-in defaults (50 KB / 500 KB) are used.  Set to
    #: ``project_config.pipeline.conformance`` to make ``pipeline.yaml`` thresholds
    #: effective for impl-fidelity conformance assessments (ERROR 4 fix).
    conformance_config: ConformanceConfig | None = None
    #: Fast-mode tests-green floor runner (AG3-018, FK-24 §24.3.4). A callable
    #: ``runner(story_dir) -> (green, reason)`` — the SAME tests-green mechanism
    #: the closure Sanity-Gate uses (``ProductiveSanityGatePort.test_runner``),
    #: not a second one. ``None`` => the floor is unconfirmable and the fast
    #: QA-subflow FAILS CLOSED (a fast story without a confirmed test result must
    #: not pass the floor; NO ERROR BYPASSING).
    fast_test_runner: Callable[[Path], tuple[bool, str | None]] | None = None
    qa_cycle_lifecycle: _qa.QaCycleLifecycle = field(
        default_factory=_qa.QaCycleLifecycle
    )
    remediation_loop_controller: _qa.RemediationLoopController = field(
        default_factory=_qa.RemediationLoopController
    )
    #: Layer-2 review-completion sink (FK-27 §27.4.3 / §27.5.5). After each
    #: Layer-2 review envelope write succeeds, the QA-subflow emits an
    #: ``llm_call_complete`` fact (per reviewer role) through this sink so the
    #: ``guard.multi_llm`` recurring guard counts a completed review (NOT a bare
    #: API response). Default is the No-op sink; the productive telemetry adapter
    #: is wired via ``composition_root.build_verify_system``.
    review_completion_sink: ReviewCompletionSink = _NULL_REVIEW_COMPLETION_SINK
    #: Layer-3 adversarial spawner (FK-27 §27.6 / FK-48 §48.2, AG3-044). After
    #: Layer 2 yields BLOCKING findings, ``run_qa_subflow`` derives mandatory
    #: :class:`AdversarialTarget` from them, materialises the protected sandbox +
    #: ``ADVERSARIAL_TEST_SANDBOX`` envelope and carries the resulting
    #: ``agents_to_spawn`` orders out through ``QaSubflowOutcome.adversarial_spawn``
    #: so the orchestrator spawns the adversarial worker on phase re-entry. This
    #: is the productive wiring that makes the spawn non-dead on the real QA path
    #: (it is no longer reached only by hand-wired tests). ``None`` keeps the pure
    #: passthrough (no spawn derivation) for unit fixtures.
    adversarial_spawner: AdversarialSpawner | None = None
    #: Independent System/Trust-B change evidence used by the FK-24
    #: implementation terminality precondition. This is the same port type the
    #: structural Layer-1 checks use; production wires the git-backed provider.
    implementation_change_evidence_port: ChangeEvidencePort = (
        ABSENT_CHANGE_EVIDENCE_PORT
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
        defaults: VerifySystemDefaultOptions | None = None,
        **overrides: object,
    ) -> VerifySystem:
        """Construct a ``VerifySystem`` with default sub-components."""
        return _create_default(
            cls,
            artifact_manager=artifact_manager,
            defaults=resolve_default_options(defaults, overrides),
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
        """Execute the full QA-subflow and return a structured outcome."""
        return _run_qa_subflow(
            self,
            ctx,
            story_id,
            qa_context,
            target,
            review_input=review_input,
            previous_findings=previous_findings,
        )

    def _derive_adversarial_spawn(
        self,
        ctx: VerifyContextBundle,
        story_id: str,
        layer_kinds: tuple[QALayerKind, ...],
        layer_results: list[LayerResult],
    ) -> tuple[SpawnRequest, ...]:
        """Build the Layer-3 adversarial spawn orders (FK-27 §27.6 / FK-48 §48.2).

        Collects the BLOCKING findings of this round's Layer-2 reviewers
        (``qa_review`` / ``semantic_review`` / ``doc_fidelity``), derives one
        mandatory :class:`AdversarialTarget` per finding via the Layer-3
        challenger, then asks the wired :class:`AdversarialSpawner` to
        materialise the protected sandbox + ``ADVERSARIAL_TEST_SANDBOX`` envelope
        and produce the typed ``agents_to_spawn`` orders. This is the productive
        bridge that makes the spawn reachable on the real QA path (no dead path).

        Returns an empty tuple when Layer 3 was not routed (Exploration / fast),
        when no spawner is wired (unit fixtures), or when Layer 2 produced no
        BLOCKING finding. Per FK-27 §27.6 the adversarial spawn fires only on the
        real QA path when Layer-2 yields BLOCKING findings with test anchors.

        Args:
            ctx: The run-time verify-context bundle (sandbox scope / run id).
            story_id: The authoritative story display id (the one
                ``run_qa_subflow`` was invoked with), used to scope the sandbox.
            layer_kinds: The routed layer kinds (Layer 3 routed iff
                ``ADVERSARIAL`` is present).
            layer_results: The collected layer results of this round.

        Returns:
            The typed adversarial spawn orders (possibly empty).
        """
        if QALayerKind.ADVERSARIAL not in layer_kinds:
            return ()
        spawner = self.adversarial_spawner
        if spawner is None:
            return ()
        layer2_blocking = [
            finding
            for result in layer_results
            if result.layer in _LAYER_2_ROLE_NAMES
            for finding in result.findings
            if finding.severity is Severity.BLOCKING
        ]
        targets = spawner.derive_targets(layer2_blocking)
        if not targets:
            return ()
        request = spawner.request_spawn(ctx, targets, story_id=story_id)
        logger.info(
            "adversarial spawn requested (FK-27 §27.6): story_id=%s targets=%d",
            story_id,
            len(targets),
        )
        return request.agents_to_spawn

    # ------------------------------------------------------------------
    # Fast-mode floor (AG3-018, FK-24 §24.3.4)
    # ------------------------------------------------------------------

    def _run_fast_floor(
        self,
        *,
        ctx: VerifyContextBundle,
        story_id: str,
        story_ctx: StoryContext | None,
    ) -> QaSubflowOutcome:
        """Run the fast-mode QA floor: Layer 1 (structural) + tests-green."""
        return _run_fast_floor(
            self,
            ctx=ctx,
            story_id=story_id,
            story_ctx=story_ctx,
        )

    def _fast_tests_green_finding(self, story_dir: Path) -> Finding | None:
        """Run the fast-mode tests-green floor; return a BLOCKING finding on fail.

        Returns ``None`` when the injected ``fast_test_runner`` confirms tests
        green. Returns a BLOCKING SYSTEM finding when the runner reports red tests
        OR when no runner is wired (fail-closed: the floor is unconfirmable, so a
        fast story must not pass it -- NO ERROR BYPASSING).
        """
        if self.fast_test_runner is None:
            return Finding(
                layer="structural",
                check="fast_tests_green",
                severity=Severity.BLOCKING,
                message=(
                    "fast-mode tests-green floor has no live test runner wired "
                    "(AG3-018); cannot confirm tests green -> fail-closed "
                    "(FK-24 §24.3.4, NO ERROR BYPASSING)"
                ),
                trust_class=TrustClass.SYSTEM,
            )
        green, reason = self.fast_test_runner(story_dir)
        if green:
            return None
        return Finding(
            layer="structural",
            check="fast_tests_green",
            severity=Severity.BLOCKING,
            message=reason or "fast-mode tests are not green",
            trust_class=TrustClass.SYSTEM,
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
        for spec in _artifact_specs.SONARQUBE_GATE_ARTIFACTS:
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
        qa_cycle_round: int,
        previous_findings: tuple[Finding, ...],
    ) -> None:
        """Execute a non-gate data layer and write its envelope(s)."""
        _run_data_layer_kind(
            self,
            kind=kind,
            ctx=ctx,
            story_id=story_id,
            now_str=now_str,
            qa_cycle_fields=qa_cycle_fields,
            effective_review_input=effective_review_input,
            story_ctx=story_ctx,
            layer_results=layer_results,
            artifact_refs_written=artifact_refs_written,
            qa_cycle_round=qa_cycle_round,
            previous_findings=previous_findings,
        )

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

    def _structural_are_enabled(self) -> bool:
        """Return whether the structural layer's ARE gate is active (FIX-2).

        FK-27 §27.4.4: the ARE stage is only expected for the fail-closed
        missing-stage check when ``features.are == true``. The activation lives
        on the Layer-1 ``StructuralChecker``'s ARE provider; reading it here
        keeps ONE ARE-activation truth (no second flag). A non-structural Layer-1
        double (test stub) has no provider -> ARE not expected (``False``).
        """
        from agentkit.verify_system.structural.checker import StructuralChecker

        layer_1 = self.layer_1
        if isinstance(layer_1, StructuralChecker):
            return layer_1.are_enabled
        return False

    def _layer2_pairs(
        self,
) -> tuple[tuple[QALayer, _artifact_specs._LayerArtifactSpec], ...]:
        """Return (reviewer, spec) pairs for the three Layer-2 reviewers.

        Returns:
            Tuple of (QALayer, _LayerArtifactSpec) for qa_review,
            semantic_review, doc_fidelity in that order.
        """
        return (
            (self.layer_2a, _artifact_specs.LAYER_2_SPECS[0]),
            (self.layer_2b, _artifact_specs.LAYER_2_SPECS[1]),
            (self.layer_2c, _artifact_specs.LAYER_2_SPECS[2]),
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
        target_type = _artifact_specs.ARTIFACT_CLASS_TO_TARGET_TYPE.get(
            target.artifact_class
        )
        if target_type is None:
            known = ", ".join(
                str(c) for c in _artifact_specs.ARTIFACT_CLASS_TO_TARGET_TYPE
            )
            msg = (
                "Cannot resolve VerifyTargetType for "
                f"artifact_class={target.artifact_class!r}. Known classes: {known}"
            )
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
        from agentkit.story_context_manager.types import StoryMode
        from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput as _L2Input

        effective_ri = review_input if isinstance(review_input, _L2Input) else None

        try:
            # AG3-035: StoryContext wird via Injection uebergeben
            # (story_context-Parameter), nicht via direktem state_backend.store-Import.
            # Der Aufrufer (run_qa_subflow) laedt den StoryContext einmalig und
            # reicht ihn hier ein (BC-Topologie-konform).
            # Fallback auf IMPLEMENTATION-Stub wenn kein StoryContext verfuegbar
            # (Testpfad ohne persistierten Kontext, FK-27 §27.4). FIX-A: the stub
            # story type comes from the SAME _effective_story_type helper the
            # policy decision uses, so the layer run and the policy decision can
            # never diverge on the effective type (single effective-type truth).
            if story_context is not None and isinstance(story_context, StoryContext):
                layer_ctx = story_context
            else:
                layer_ctx = StoryContext(
                    project_key="verify-system-run",
                    story_id=story_id,
                    story_type=_effective_story_type(story_context),
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
        spec: _artifact_specs._LayerArtifactSpec,
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
            stage=_artifact_specs.POLICY_ARTIFACT_SPEC.stage,
            attempt=ctx.attempt,
            producer=Producer(
                type=_artifact_specs.POLICY_ARTIFACT_SPEC.producer_type,
                name=_artifact_specs.POLICY_ARTIFACT_SPEC.producer_name,
                id=ProducerId(
                    f"{_artifact_specs.POLICY_ARTIFACT_SPEC.producer_name}-"
                    f"{ctx.run_id}-{ctx.attempt}"
                ),
            ),
            started_at=datetime.fromisoformat(now_str),
            finished_at=datetime.fromisoformat(now_str),
            status=EnvelopeStatus.PASS if decision.passed else EnvelopeStatus.FAIL,
            artifact_class=ArtifactClass.QA,
            payload=payload,
        )
        self.artifact_manager.write(envelope)
        return _artifact_specs.POLICY_ARTIFACT_SPEC.filename




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


def _run_data_layer_kind(
    system: VerifySystem,
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
    qa_cycle_round: int,
    previous_findings: tuple[Finding, ...],
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
        effective_review_input: Normalised Layer-2 review input.
        story_ctx: Pre-resolved ``StoryContext`` (or ``None``).
        layer_results: Mutable accumulator of layer results (appended in
            place).
        artifact_refs_written: Mutable accumulator of artefact filenames
            (appended in place).
        qa_cycle_round: 1-based QA-cycle round (``> 1`` => remediation;
            passed to the LLM runner for finding-resolution).
        previous_findings: Prior-round findings carried into the LLM
            runner's remediation bundle (DK-04 §4.6).
    """
    self = system
    if kind is QALayerKind.LLM_EVALUATOR:
        results = _run_layer2(
            self,
            ctx=ctx,
            story_id=story_id,
            kind=kind,
            effective_review_input=effective_review_input,
            story_ctx=story_ctx,
            qa_cycle_round=qa_cycle_round,
            previous_findings=previous_findings,
        )
        pairs = list(zip(results, _artifact_specs.LAYER_2_SPECS, strict=True))
    else:
        layer_instance = self._layer_for_kind(kind)
        result = self._execute_layer(
            layer_instance, ctx, story_id, kind,
            review_input=effective_review_input,
            story_context=story_ctx,
        )
        pairs = [(result, spec) for spec in _kind_to_single_artifacts(kind)]

    for result, spec in pairs:
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

def _create_default(
    cls: type[VerifySystem],
    *,
    artifact_manager: ArtifactManager,
    defaults: VerifySystemDefaultOptions,
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
        review_completion_sink: Optionaler produktiver
            ``ReviewCompletionSink`` (FK-27 §27.4.3 / §27.5.5): emittiert pro
            erfolgreichem Layer-2-Review-Artefakt-Write ein
            ``llm_call_complete``-Event (mit Reviewer-Rolle im Payload),
            damit der ``guard.multi_llm`` Gate 2 einen abgeschlossenen Review
            zaehlt (nicht die blosse API-Antwort). ``None`` => No-op-Sink
            (Testpfad). Produktive Aufrufer reichen den telemetrie-gebundenen
            Sink via ``composition_root.build_verify_system`` ein.
        layer2_llm_client: Optionaler ``LlmClient`` (AG3-043 E6, FK-27
            §27.5). Wenn gesetzt, baut der QA-Subflow pro Run einen
            ``ParallelEvalRunner`` (FK-44 §44.4.2) und faehrt die drei
            LLM-Bewertungen WIRKLICH (kein Rueckfall auf die
            deterministischen Stub-Reviewer); ``None`` => Reviewer-Pfad.
            Produktiv via ``composition_root.build_verify_system``.
        fast_test_runner: Optional fast-mode tests-green floor runner
            (AG3-018, FK-24 §24.3.4). In ``mode == fast`` the QA-subflow
            degenerates to Layer 1 (structural) + the hard tests-green floor
            and SKIPS Layers 2-4 + the feedback loop. The runner is the SAME
            mechanism the closure Sanity-Gate uses; ``None`` => the floor is
            unconfirmable and the fast subflow FAILS CLOSED.

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
    resolved_port = defaults.story_context_port or _NULL_STORY_CONTEXT_PORT
    resolved_sonar_port = defaults.sonar_gate_port or ABSENT_SONAR_GATE_PORT
    # AG3-042: the FK-27 §27.4 Layer-1 stage registry is bound to BOTH the
    # StructuralChecker (drives the checks) and the PolicyEngine (drives the
    # fail-closed missing-artifact check, FK-33 §33.7) -- ONE registry truth
    # shared by both sub-components (no second stage truth). The PRODUCTIVE
    # composition root (``build_verify_system``) injects the full FK-27
    # §27.4 catalogue together with the live telemetry / build-test / ARE
    # ports. A bare ``create_default`` (test path) defaults to the
    # meta-only Layer 1: the structural layer runs only the canonical-state
    # pre-checks unless the caller wires the registry + evidence ports
    # (preserving the pre-AG3-042 default behaviour for unit fixtures).
    from agentkit.verify_system.stage_registry.registry import (
        StageRegistry as _StageRegistry,
    )
    from agentkit.verify_system.structural.checker import StructuralChecker

    # Meta-only default (empty registry) when the caller wires no registry:
    # the structural layer runs only the canonical-state pre-checks and the
    # policy engine demands no Layer-1 stages. The productive root injects
    # the full FK-27 §27.4 catalogue.
    resolved_registry: StageRegistry = (
        defaults.stage_registry
        if defaults.stage_registry is not None
        else _StageRegistry(stages=())
    )
    structural_checker = StructuralChecker(
        registry=resolved_registry,
        telemetry=defaults.structural_telemetry_port,
        build_test_port=defaults.structural_build_test_port,
        are_provider=defaults.structural_are_provider,
        change_evidence_port=defaults.structural_change_evidence_port,
    )
    # AG3-044 (FK-27 §27.6 / FK-48 §48.2): the adversarial spawner is wired
    # by default (it only needs the producer-bound ArtifactManager). It is
    # held BOTH on the Layer-3 challenger (so ``derive_adversarial_targets``
    # turns BLOCKING Layer-2 findings into mandatory targets) AND on the
    # VerifySystem (so ``run_qa_subflow`` calls ``request_spawn`` to
    # materialise the protected sandbox + carry the spawn orders out). This
    # is the end-to-end wiring that makes the spawn reachable on the real QA
    # path -- no dead path.
    adversarial_spawner = AdversarialSpawner(artifact_manager)
    # AG3-015 / FK-44 §44.4.2: the QA layers materialize their prompts via
    # PromptRuntime.materialize_prompt and audit them via the
    # ArtifactManager. Both dependencies are injected here so no layer
    # reaches into prompt-runtime sub-modules or state_backend.store.
    return cls(
        layer_1=structural_checker,
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
            spawner=adversarial_spawner,
        ),
        policy_engine=PolicyEngine(
            max_major_findings=defaults.max_major_findings,
            stage_registry=resolved_registry,
        ),
        artifact_manager=artifact_manager,
        story_context_port=resolved_port,
        sonar_gate_port=resolved_sonar_port,
        layer2_llm_client=defaults.layer2_llm_client,
        conformance_emitter=defaults.conformance_emitter,
        conformance_config=defaults.conformance_config,
        fast_test_runner=defaults.fast_test_runner,
        remediation_loop_controller=(
            _qa.RemediationLoopController(
                max_feedback_rounds=defaults.max_feedback_rounds
            )
            if defaults.max_feedback_rounds is not None
            else _qa.RemediationLoopController()
        ),
        qa_cycle_lifecycle=(
            _qa.QaCycleLifecycle(invalidation_sink=defaults.invalidation_sink)
            if defaults.invalidation_sink is not None
            else _qa.QaCycleLifecycle()
        ),
        review_completion_sink=(
            defaults.review_completion_sink
            if defaults.review_completion_sink is not None
            else _NULL_REVIEW_COMPLETION_SINK
        ),
        adversarial_spawner=adversarial_spawner,
        implementation_change_evidence_port=(
            defaults.structural_change_evidence_port
            if defaults.structural_change_evidence_port is not None
            else ABSENT_CHANGE_EVIDENCE_PORT
        ),
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
    self = system
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
            qa_cycle_round=cycle_state.round,
            previous_findings=previous_findings,
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
    from agentkit.verify_system.remediation.feedback import build_feedback
    from agentkit.verify_system.remediation.finding_resolution import (
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
    feedback = build_feedback(
        decision, story_id, ctx.attempt, finding_resolution=resolution_map
    )

    # Step 8: AG3-041 §2.1.7 -- run the remediation loop controller AFTER
    # the policy engine (or the Sonar fail-closed decision, FK-27 §27.6a.2).
    # PASS -> CONTINUE_TO_CLOSURE; FAIL + round < max -> CONTINUE_REMEDIATION;
    # FAIL + round >= max -> ESCALATE (hard, FK-27 §27.2.2
    # max_rounds_exceeded). escalated forces verdict=FAIL. The Sonar
    # fail-closed verdict traverses the SAME loop (no bypass, no fail-open).
    #
    # FIX-5 (FK-27 §27.4.2/§27.4.5): an ``impact.violation`` BLOCKING FAIL
    # routes DIRECTLY to ESCALATED -- "Eskalation an Mensch, kein
    # Ruecksprung", no Worker-feedback loop. The structural layer stamps
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
#: FK-27 §27.5 Layer-2 reviewer role names (qa_review / semantic_review /
#: doc_fidelity). Used to collect the Layer-2 BLOCKING findings the adversarial
#: spawn derives mandatory targets from (FK-27 §27.6 / FK-48 §48.2, AG3-044).
_LAYER_2_ROLE_NAMES: frozenset[str] = frozenset(
    {"qa_review", "semantic_review", "doc_fidelity"}
)


def _layer_escalation_requested(layer_results: tuple[LayerResult, ...]) -> bool:
    """Whether any layer stamped an immediate-escalation request (FIX-5).

    FK-27 §27.4.2/§27.4.5: the structural layer sets
    ``metadata["escalated"]=True`` when an ``escalated`` stage
    (``impact.violation``) FAILs BLOCKING. Such a finding must escalate
    immediately to a human -- it must NOT traverse the normal remediation loop.
    """
    return any(lr.metadata.get("escalated") is True for lr in layer_results)


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
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.types import StoryType

    if isinstance(story_ctx, StoryContext):
        return story_ctx.story_type
    return StoryType.IMPLEMENTATION


def _max_layer_reached(layer_results: list[LayerResult]) -> int:
    """Derive the highest QA layer that produced a result (FK-33 §33.7.2)."""
    registry = StageRegistry()
    reached = [
        stage.layer
        for stage_id in _produced_stage_ids(layer_results, registry)
        if (stage := registry.stage_for_id(stage_id)) is not None
    ]
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
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.story_model import WireStoryMode

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
       the three evaluations. "Reviews finden IMMER statt" (FK-27 §27.5): when
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

    from agentkit.verify_system.llm_evaluator.layer2_integration import (
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
    )


def _normalise_layer2_input(effective_review_input: object | None) -> Layer2ReviewInput:
    """Return a concrete ``Layer2ReviewInput`` (empty default when not one)."""
    from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput as _L2Input

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
) -> FidelityContext | None:
    """Build the implementation-fidelity context when StoryContext is available."""
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.types import StoryType
    from agentkit.verify_system.conformance_service import FidelityContext
    from agentkit.verify_system.llm_evaluator.bundle import build_review_bundle

    if not isinstance(story_ctx, StoryContext):
        return None
    review_bundle = build_review_bundle(
        review_input,
        story_id=story_id,
        qa_cycle_round=qa_cycle_round,
        previous_findings=list(previous_findings) if previous_findings else None,
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
    from agentkit.verify_system.conformance_service import (
        ConformanceService,
        FidelityLevel,
        StructuredEvaluatorConformanceAdapter,
    )
    from agentkit.verify_system.llm_evaluator.structured_evaluator import (
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
    from agentkit.verify_system.llm_evaluator.structured_evaluator import LlmVerdict
    from agentkit.verify_system.remediation.finding_resolution import (
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
    from agentkit.story_context_manager.models import StoryContext

    if not isinstance(story_ctx, StoryContext):
        return None
    from agentkit.verify_system.llm_evaluator.parallel_runner import ParallelEvalRunner
    from agentkit.verify_system.llm_evaluator.prompt_materializer import (
        PromptRuntimeMaterializer,
    )
    from agentkit.verify_system.llm_evaluator.structured_evaluator import (
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
