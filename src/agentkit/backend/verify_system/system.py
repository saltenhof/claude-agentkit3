"""Top surface of the verify-system bounded context."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from agentkit.backend.artifacts import (
    ArtifactEnvelope,
    ArtifactManager,
    ArtifactReference,
    EnvelopeStatus,
    Producer,
    ProducerId,
)
from agentkit.backend.core_types import ArtifactClass, PolicyVerdict, QaContext, SpawnRequest
from agentkit.backend.verify_system import _artifact_specs
from agentkit.backend.verify_system.adversarial_orchestrator.challenger import (
    AdversarialChallenger,
)
from agentkit.backend.verify_system.adversarial_orchestrator.spawn import AdversarialSpawner
from agentkit.backend.verify_system.contract import (
    QaSubflowOutcome,
    VerifyContextBundle,
    VerifyTarget,
)
from agentkit.backend.verify_system.defaults import (
    VerifySystemDefaultOptions,
    resolve_default_options,
)
from agentkit.backend.verify_system.errors import (
    LayerExecutionError,
    VerifySystemError,
    VerifyTargetUnknownError,
)
from agentkit.backend.verify_system.llm_evaluator.reviewer import (
    DocFidelityReviewer,
    QaReviewReviewer,
    SemanticReviewer,
)
from agentkit.backend.verify_system.policy_engine.engine import PolicyEngine, VerifyDecision
from agentkit.backend.verify_system.protocols import (
    Finding,
    LayerResult,
    QALayer,
    RunScope,
    Severity,
    StoryContextQueryPort,
    TrustClass,
)
from agentkit.backend.verify_system.qa_cycle import integration as _qa
from agentkit.backend.verify_system.review_completion import (
    NullReviewCompletionSink,
    ReviewCompletionSink,
)
from agentkit.backend.verify_system.routing import QALayerKind
from agentkit.backend.verify_system.sonarqube_gate.port import (
    ABSENT_SONAR_GATE_PORT,
    SonarGateInputPort,
)
from agentkit.backend.verify_system.sonarqube_gate.stage_runner import (
    SonarStageResult,
    run_sonarqube_gate_stage,
)
from agentkit.backend.verify_system.structural.system_evidence import (
    ABSENT_CHANGE_EVIDENCE_PORT,
    ChangeEvidencePort,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.config.models import ConformanceConfig
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.telemetry.emitters import EventEmitter
    from agentkit.backend.verify_system.llm_evaluator import LlmClient, ParallelEvalRunner
    from agentkit.backend.verify_system.llm_evaluator.context_sufficiency import (
        ContextSufficiencyResult,
    )
    from agentkit.backend.verify_system.stage_registry.registry import StageRegistry

from agentkit.backend.verify_system.fast_mode_floor import _run_fast_floor
from agentkit.backend.verify_system.qa_execution import _run_qa_subflow
from agentkit.backend.verify_system.remediation_feedback import (
    _mandatory_target_feedback_findings as _mandatory_target_feedback_findings,
)
from agentkit.backend.verify_system.routed_layer_execution import (
    _DataLayerInputs,
    _run_data_layer_kind,
)
from agentkit.backend.verify_system.story_contract_resolution import (
    _effective_story_type,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _NullStoryContextPort:
    """No-op ``StoryContextQueryPort``: always returns ``None``.

    Default for ``VerifySystem`` without an injected state-backed adapter
    (test path without DB). Preserves the historical fallback behaviour onto the
    IMPLEMENTATION stub in ``_execute_layer`` (AG3-035).
    """

    def load(self, story_dir: Path) -> StoryContext | None:
        """Return ``None``; the no-op port ignores ``story_dir``.

        Args:
            story_dir: Story working directory (not consumed by the no-op port).
        """
        del story_dir  # No-op port does not use the path (protocol param, S1172).
        return None

    def resolve_run_scope(self, story_dir: Path) -> RunScope | None:
        """Return ``None``; without a state backend no run correlation is known.

        Args:
            story_dir: Story working directory (not consumed by the no-op port).
        """
        del story_dir  # No-op port does not use the path (protocol param, S1172).
        return None


@dataclass(frozen=True)
class VerifySystem:
    """Top surface of the verify-system Capability-BC.

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
        layer_2a: Layer-2a QA-review reviewer (test quality/coverage).
        layer_2b: Layer-2b semantic reviewer (concept fidelity/naming).
        layer_2c: Layer-2c doc-fidelity reviewer (docstrings/ADR).
        layer_3: Layer-3 adversarial orchestrator.
            Must satisfy :class:`QALayer` protocol.
        policy_engine: Layer-4 deterministic aggregator.
        artifact_manager: ArtifactManager for writing QA artefacts.
        story_context_port: Injected read-port for resolving the
            ``StoryContext`` (AG3-035). Default is a no-op port; the
            productive state-backed adapter is wired via
            ``composition_root.build_verify_system``. Eliminates the
            direct ``state_backend.store`` import in ``run_qa_subflow``.
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
    story_context_port: StoryContextQueryPort = field(
        default_factory=_NullStoryContextPort
    )
    sonar_gate_port: SonarGateInputPort = ABSENT_SONAR_GATE_PORT
    layer2_runner: ParallelEvalRunner | None = None
    layer2_llm_client: LlmClient | None = None
    conformance_emitter: EventEmitter | None = None
    #: FK-32 §32.4b.3 prompt-size thresholds for the ConformanceService. ``None``
    #: => the service's built-in defaults (50 KB / 500 KB) are used.  Set to
    #: ``project_config.pipeline.conformance`` to make ``pipeline.yaml`` thresholds
    #: effective for impl-fidelity conformance assessments (ERROR 4 fix).
    conformance_config: ConformanceConfig | None = None
    layer2_bundle_token_limit: int = 32_000
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
    #: Default Layer-2 review-completion sink (FK-27 §27.4.3 / §27.5.5): a No-op
    #: that drops ``llm_call_complete`` emissions on the test path. NOT a guard
    #: weakening: ``guard.multi_llm`` counts canonical events, so a dropped
    #: emission leaves the per-role count at 0 -> BLOCKING FAIL (fail-closed).
    #: The productive telemetry adapter is wired via
    #: ``composition_root.build_verify_system``.
    review_completion_sink: ReviewCompletionSink = field(
        default_factory=NullReviewCompletionSink
    )
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

    @property
    def stage_registry(self) -> StageRegistry:
        """Return the StageRegistry used by the policy engine (FK-33 §33.2.1).

        Exposed for callers that need per-check ``origin_check_ref`` lookups
        (AG3-078 ERROR 1: build check_id -> origin_check_ref mapping before
        emitting qa_check_outcomes). The registry is the single source of truth
        for all stage definitions including FC-derived checks.

        Returns:
            The :class:`~agentkit.backend.verify_system.stage_registry.registry.StageRegistry`
            bound to the policy engine.
        """
        return self.policy_engine._registry  # noqa: SLF001

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
        :meth:`agentkit.backend.verify_system.policy_engine.engine.PolicyEngine.decide`.

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

    def _load_story_context_for_qa(self, story_dir: Path) -> StoryContext | None:
        """Load the QA story context through the injected query port."""
        return self.story_context_port.load(story_dir)

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
        # FK-48 §48.2.2 (AG3-079): mandatory targets are derived from Layer-2
        # findings of finding_type ``assertion_weakness`` (status FAIL/
        # PASS_WITH_CONCERNS), NOT pauschal per BLOCKING finding. Pass the FULL
        # Layer-2 findings so the assertion_weakness filter decides; the
        # remediation round is the QA-subflow attempt (FK-48 §48.2.2 source).
        # FK-27 §27.5 Layer-2 reviewer role names (qa_review / semantic_review /
        # doc_fidelity). Used here to collect Layer-2 BLOCKING findings that the
        # adversarial spawn derives mandatory targets from (FK-48 §48.2, AG3-044).
        _layer2_roles: frozenset[str] = frozenset(
            {"qa_review", "semantic_review", "doc_fidelity"}
        )
        layer2_checks = [
            finding
            for result in layer_results
            if result.layer in _layer2_roles
            for finding in result.findings
        ]
        targets = spawner.extract_mandatory_targets(layer2_checks, ctx.attempt)
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
        layer_results: list[LayerResult],
        artifact_refs_written: list[str],
        inputs: _DataLayerInputs,
    ) -> None:
        """Execute a non-gate data layer and write its envelope(s)."""
        _run_data_layer_kind(
            self,
            kind=kind,
            ctx=ctx,
            story_id=story_id,
            now_str=now_str,
            qa_cycle_fields=qa_cycle_fields,
            layer_results=layer_results,
            artifact_refs_written=artifact_refs_written,
            inputs=inputs,
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
        from agentkit.backend.verify_system.structural.checker import StructuralChecker

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
        from agentkit.backend.story_context_manager.models import StoryContext
        from agentkit.backend.story_context_manager.types import StoryMode
        from agentkit.backend.verify_system.llm_evaluator.inputs import Layer2ReviewInput as _L2Input

        effective_ri = review_input if isinstance(review_input, _L2Input) else None

        try:
            # AG3-035: the StoryContext is passed via injection
            # (story_context parameter), not via a direct state_backend.store import.
            # The caller (run_qa_subflow) loads the StoryContext once and
            # passes it in here (BC-topology-conformant).
            # Fallback onto the IMPLEMENTATION stub when no StoryContext is available
            # (test path without persisted context, FK-27 §27.4). FIX-A: the stub
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
        """Write a single layer envelope via the ArtifactManager.

        AG3-026 §AK7: one ``ArtifactEnvelope`` per layer-artifact spec
        with the associated producer + stage.
        W1: Layer-2 envelopes now carry standalone LayerResult
        payloads per reviewer (no more synthetic payload repeat).

        AG3-026 §AK8: QA-cycle fields (``qa_cycle_id``,
        ``qa_cycle_round``, ``evidence_epoch``, ``evidence_fingerprint``)
        are embedded from ``ctx.phase_envelope`` (now ``PhaseEnvelopeView``)
        into each envelope payload, when set there.
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
        """Write the policy-decision envelope (``decision.json``).

        AG3-026 §AK7: the filename is ``decision.json`` (canonical per FK-27 §27.7;
        stage ``qa-policy-decision``; not the old dash form ``verify-decision.json``
        / ``qa-verify-decision``).
        QA-cycle fields are embedded analogously to layer artifacts.

        Returns:
            ``"decision.json"`` (FK-27 §27.7 / AG3-026 §AK7).
        """
        from agentkit.backend.verify_system.policy_engine.projections import (
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

    def _run_context_sufficiency_pre_step(
        self,
        *,
        ctx: VerifyContextBundle,
        story_id: str,
        now_str: str,
        qa_cycle_fields: dict[str, object],
        review_input: object | None,
        story_ctx: object | None,
    ) -> ContextSufficiencyResult:
        """Build and persist ``context_sufficiency.json`` before Layer 2."""
        from agentkit.backend.story_context_manager.models import StoryContext
        from agentkit.backend.verify_system.llm_evaluator.context_sufficiency import (
            ContextSufficiencyBuilder,
            SufficiencyLevel,
        )
        from agentkit.backend.verify_system.llm_evaluator.inputs import Layer2ReviewInput

        effective_input = (
            review_input
            if isinstance(review_input, Layer2ReviewInput)
            else Layer2ReviewInput()
        )
        worktree_root = (
            story_ctx.project_root
            if isinstance(story_ctx, StoryContext) and story_ctx.project_root is not None
            else None
        )
        builder = ContextSufficiencyBuilder.from_story_dir(
            story_id=story_id,
            story_dir=ctx.story_dir,
            worktree_root=worktree_root,
        )
        result = builder.build(
            effective_input,
            caller_diff_summary=builder.caller_diff_summary(),
            caller_evidence_manifest=(
                ctx.evidence_manifest
                if ctx.evidence_manifest is not None
                else builder.caller_evidence_manifest()
            ),
        )
        payload = result.artifact.model_dump(mode="json")
        payload.update(qa_cycle_fields)
        spec = _artifact_specs.CONTEXT_SUFFICIENCY_ARTIFACT_SPEC
        envelope = ArtifactEnvelope(
            schema_version="3.0",
            story_id=story_id,
            run_id=ctx.run_id,
            stage=spec.stage,
            attempt=ctx.attempt,
            producer=Producer(
                type=spec.producer_type,
                name=spec.producer_name,
                id=ProducerId(f"{spec.producer_name}-{ctx.run_id}-{ctx.attempt}"),
            ),
            started_at=datetime.fromisoformat(now_str),
            finished_at=datetime.fromisoformat(now_str),
            status=(
                EnvelopeStatus.PASS
                if result.sufficiency is SufficiencyLevel.SUFFICIENT
                else EnvelopeStatus.WARN
            ),
            artifact_class=ArtifactClass.QA,
            payload=payload,
        )
        self.artifact_manager.write(envelope)
        return result


def _build_qa_cycle_lifecycle(
    defaults: VerifySystemDefaultOptions,
) -> _qa.QaCycleLifecycle:
    """Build the QA-cycle lifecycle with its invalidation sink + push-barrier gate.

    AG3-147 (FK-10 §10.2.4b boundary type 2): the QA-cycle-boundary push barrier
    gate is injected here (defaulting to the no-op gate when unwired). The
    composition root supplies the productive control-plane-delegating gate.
    """
    from agentkit.backend.verify_system.qa_cycle.lifecycle import (
        NULL_QA_CYCLE_PUSH_BARRIER_GATE,
    )

    gate = defaults.qa_cycle_push_barrier_gate or NULL_QA_CYCLE_PUSH_BARRIER_GATE
    invalidation_sink = defaults.invalidation_sink
    fingerprint_source = defaults.qa_cycle_fingerprint_source
    if invalidation_sink is not None and fingerprint_source is not None:
        return _qa.QaCycleLifecycle(
            invalidation_sink=invalidation_sink,
            push_barrier_gate=gate,
            fingerprint_source=fingerprint_source,
        )
    if invalidation_sink is not None:
        return _qa.QaCycleLifecycle(
            invalidation_sink=invalidation_sink,
            push_barrier_gate=gate,
        )
    if fingerprint_source is not None:
        return _qa.QaCycleLifecycle(
            push_barrier_gate=gate,
            fingerprint_source=fingerprint_source,
        )
    return _qa.QaCycleLifecycle(push_barrier_gate=gate)


def _create_default(
    cls: type[VerifySystem],
    *,
    artifact_manager: ArtifactManager,
    defaults: VerifySystemDefaultOptions,
) -> VerifySystem:
    """Construct a ``VerifySystem`` with default sub-components.

    Builds all sub-components with sensible defaults.
    ``artifact_manager`` is a **mandatory argument** (AG3-026 §2.1.4 +
    re-review finding 3): a missing ArtifactManager was
    story-explicitly marked as a fail-closed path; a silent
    no-op variant would silently discard QA truth.

    Args:
        artifact_manager: ``ArtifactManager`` for artifact writes.
            **Mandatory**. Callers that need a test stub
            supply a recording test double; productive callers
            use ``bootstrap.composition_root.build_verify_system``.
        max_major_findings: Threshold for the policy engine. Mirrors
            :class:`PolicyEngine` -- MAJOR findings beyond this count
            turn into blocking findings (FK-27 §27.4.2 / §27.7.2).
        max_feedback_rounds: Ceiling for the subflow-internal remediation
            loop (FK-03 §3.4.2 / FK-38; resolved from the pipeline config by
            ``build_verify_system``). ``None`` => the controller's default
            (3). The :class:`RemediationLoopController` is the hard owner of
            the ceiling — it is NOT bypassable (NO ERROR BYPASSING).
        story_context_port: Optional ``StoryContextQueryPort`` (AG3-035).
            When ``None``, the no-op port is used (fallback onto the
            IMPLEMENTATION stub in ``_execute_layer``). Productive callers
            pass in the state-backed adapter via
            ``composition_root.build_verify_system``.
        sonar_gate_port: Optional ``SonarGateInputPort`` (AG3-052,
            FK-33 §33.6). When ``None``, the absent-Sonar port is
            used (``sonarqube.available == false`` => stage SKIP).
        invalidation_sink: Optional productive
            ``ArtifactInvalidationSink`` (FK-27 §27.2.3 / AG3-041 §2.1.3):
            emits an ``artifact_invalidated`` telemetry event per
            ``stale/`` move. ``None`` => no-op sink (test path without
            wired telemetry). Productive callers pass in the
            telemetry-bound sink via
            ``composition_root.build_verify_system``.
        review_completion_sink: Optional productive
            ``ReviewCompletionSink`` (FK-27 §27.4.3 / §27.5.5): emits an
            ``llm_call_complete`` event (with the reviewer role in the
            payload) per successful Layer-2 review-artifact write,
            so the ``guard.multi_llm`` Gate 2 counts a completed review
            (not the bare API response). ``None`` => no-op sink
            (test path). Productive callers pass in the telemetry-bound
            sink via ``composition_root.build_verify_system``.
        layer2_llm_client: Optional ``LlmClient`` (AG3-043 E6, FK-27
            §27.5). When set, the QA-subflow builds a
            ``ParallelEvalRunner`` (FK-44 §44.4.2) per run and REALLY runs
            the three LLM evaluations (no fallback onto the
            deterministic stub reviewers); ``None`` => reviewer path.
            Productively via ``composition_root.build_verify_system``.
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
            "agentkit.backend.bootstrap.composition_root.build_verify_system "
            "for the wired default.",
        )
    resolved_port = defaults.story_context_port or _NullStoryContextPort()
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
    from agentkit.backend.verify_system.stage_registry.registry import (
        StageRegistry as _StageRegistry,
    )
    from agentkit.backend.verify_system.structural.checker import StructuralChecker

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
            # AG3-079 (FK-48 §48.1.6 / FK-11 §11.8): the Layer-3 runtime drives
            # the verify-LLM-transport for the MANDATORY sparring call and writes
            # the five adversarial telemetry events. Defaults reuse the wired
            # layer2 transport / conformance emitter when no dedicated
            # adversarial collaborators are supplied (single transport surface,
            # no second pool adapter).
            sparring_client=(
                defaults.adversarial_sparring_client
                if defaults.adversarial_sparring_client is not None
                else defaults.layer2_llm_client
            ),
            telemetry_emitter=(
                defaults.adversarial_telemetry_emitter
                if defaults.adversarial_telemetry_emitter is not None
                else defaults.conformance_emitter
            ),
            sparring_resolver=defaults.adversarial_sparring_resolver,
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
        layer2_bundle_token_limit=defaults.layer2_bundle_token_limit,
        fast_test_runner=defaults.fast_test_runner,
        remediation_loop_controller=(
            _qa.RemediationLoopController(
                max_feedback_rounds=defaults.max_feedback_rounds
            )
            if defaults.max_feedback_rounds is not None
            else _qa.RemediationLoopController()
        ),
        qa_cycle_lifecycle=_build_qa_cycle_lifecycle(defaults),
        review_completion_sink=(
            defaults.review_completion_sink
            if defaults.review_completion_sink is not None
            else NullReviewCompletionSink()
        ),
        adversarial_spawner=adversarial_spawner,
        implementation_change_evidence_port=(
            defaults.structural_change_evidence_port
            if defaults.structural_change_evidence_port is not None
            else ABSENT_CHANGE_EVIDENCE_PORT
        ),
    )
