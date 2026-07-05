"""Implementation phase handler with internal QA-subflow.

E1 (AG3-026 Pass-2): ``on_enter`` calls
``verify_system.run_qa_subflow(ctx_bundle, story_id, qa_context, target)``
as the ONLY ArtifactEnvelope write path AND the ONLY layer-execution
path. ``run_qa_subflow`` now returns ``QaSubflowOutcome`` which carries
the full ``VerifyDecision``; the FK-69 path is fed directly from
``outcome.decision`` -- no second cycle run needed. QA-Read-Models are
written via ``ProjectionAccessor.record_qa_layer_artifacts`` (domain
write boundary, AG3-035 #5); ``record_verify_decision`` persists the decision.

W2 (AG3-026 Re-Review): ``ImplementationPhaseHandler`` builds a
``PhaseEnvelopeView`` from ``envelope.state.payload`` and passes it
into ``verify_system.run_qa_subflow``, avoiding a ``pipeline_engine``
import inside ``verify_system``.

AG3-044 (FK-26 §26.11.2 / FK-20 §20.5.1):

* BLOCKED-exit -- ``on_enter`` reads ``worker-manifest.json`` FIRST (before any
  QA-subflow). A ``BLOCKED`` manifest returns ``PhaseStatus.ESCALATED`` with the
  blocker details in ``suggested_reaction`` and runs NO QA-subflow (invariant
  ``worker_blocked_escalates``; NO ERROR BYPASSING -- the check is unconditional).
* Orchestrator-Trennlinie -- the handler no longer runs an inline ``while True``
  remediation loop. One QA-subflow run per ``on_enter``: PASS -> COMPLETED,
  FAIL+CONTINUE_REMEDIATION -> ``IN_PROGRESS`` with
  ``agents_to_spawn=[remediation_worker]`` (subflow-internal, no phase change),
  FAIL+ESCALATE -> ESCALATED.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.artifacts import ArtifactReference
from agentkit.backend.core_types import (
    ArtifactClass,
    QaContext,
    SpawnKind,
    SpawnReason,
    SpawnRequest,
)
from agentkit.backend.core_types.qa_artifact_names import (
    ALL_QA_ARTIFACT_FILES,
    WORKER_MANIFEST_FILE,
)
from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.implementation.manifest import WorkerManifest, WorkerManifestStatus
from agentkit.backend.installer.paths import resolve_qa_story_dir
from agentkit.backend.pipeline_engine.lifecycle import HandlerResult
from agentkit.backend.pipeline_engine.phase_executor import (
    EscalationReason,
    ImplementationPayload,
    ImplementationPhaseMemory,
    PhaseMemory,
    PhaseState,
    PhaseStatus,
    QaCycleStatus,
    evolve_phase_state,
)
from agentkit.backend.state_backend.store import (
    bind_ownership_fence_scope,
    load_flow_execution,
    load_override_records,
    record_verify_decision,
    resolve_ownership_fence_snapshot,
    save_story_context,
)
from agentkit.backend.verify_system.contract import PhaseEnvelopeView, VerifyContextBundle
from agentkit.backend.verify_system.contract import QaSubflowOutcome as _QaSubflowOutcome

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from agentkit.backend.config.models import ConformanceConfig
    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.verify_system import VerifySystem
    from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClient
    from agentkit.backend.verify_system.protocols import Finding
    from agentkit.backend.verify_system.sonarqube_gate.port import SonarGateInputPort
    from agentkit.backend.verify_system.structural.checker import AreGateProvider
    from agentkit.backend.verify_system.structural.checks import BuildTestEvidencePort

logger = logging.getLogger(__name__)


@dataclass
class ImplementationConfig:
    """Configuration for the implementation phase handler.

    Attributes:
        story_dir: Root directory of the story being verified.
        max_feedback_rounds: Maximum QA feedback rounds before escalation.
        verify_system: Optional pre-wired ``VerifySystem`` instance;
            if ``None``, built via ``composition_root.build_verify_system``.
        layer2_llm_client: Optional Layer-2 LLM transport (AG3-067 AC7). The
            composition root threads the SAME client it injects into the closure
            level-4 feedback port through here into ``build_verify_system`` so the
            productive QA-subflow Layer-2 reviewers and the post-merge
            feedback-fidelity evaluator share ONE transport (single source of
            truth). ``None`` => ``build_verify_system`` wires the fail-closed
            :class:`FailClosedLlmClient` (Layer 2 still RUNS and fails closed).
    """

    story_dir: Path | None = None
    max_feedback_rounds: int = 3
    verify_system: VerifySystem | None = None
    layer2_llm_client: LlmClient | None = None


class ImplementationPhaseHandler:
    """Run implementation and its internal QA-subflow."""

    def __init__(self, config: ImplementationConfig) -> None:
        self._config = config

    def on_enter(self, ctx: StoryContext, envelope: PhaseEnvelope) -> HandlerResult:
        """Run the implementation QA-subflow to pass or escalation.

        E1 (AG3-026 Pass-2): ``run_qa_subflow`` is the SINGLE write path
        for ArtifactEnvelopes AND the single layer-execution path.  The
        returned ``QaSubflowOutcome`` carries the full ``VerifyDecision``
        which is fed into the FK-69 recording path: QA-Read-Models via
        ``ProjectionAccessor.record_qa_layer_artifacts`` (AG3-035 #5) and the
        decision via ``record_verify_decision`` -- no second layer execution.

        W2: Builds ``PhaseEnvelopeView`` from ``envelope.state.payload``
        to avoid a ``pipeline_engine`` import inside ``verify_system``.
        """

        state = envelope.state
        s_dir = self._config.story_dir
        if s_dir is None:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=("story_dir is not configured in ImplementationConfig",),
                updated_state=_state_with_payload(
                    state,
                    QaCycleStatus.ESCALATED,
                    QaContext.IMPLEMENTATION_INITIAL,
                ),
            )

        # AG3-044 (FK-26 §26.11.2): BLOCKED-exit is checked FIRST, before any
        # QA-subflow. NO ERROR BYPASSING -- this is the unconditional first
        # action of on_enter; a BLOCKED manifest can never reach the QA-subflow.
        # Invariant worker_blocked_escalates holds on the real handler path.
        blocked_result = self._blocked_exit_result(state, s_dir)
        if blocked_result is not None:
            return blocked_result

        # AG3-069 (FK-05 §5.5.1/§5.6, AC2): IS manifest-approval pre-check.
        # For integration_stabilization stories, the implementation phase must
        # not proceed without an approved IntegrationScopeManifest (fail-closed).
        # Gated on the IS contract so standard stories are completely unaffected
        # (CORE PRINCIPLE: gate every IS enforcement on implementation_contract).
        is_approval_error = _check_is_implementation_approval(ctx, s_dir, state)
        if is_approval_error is not None:
            return is_approval_error

        save_story_context(s_dir, ctx)

        flow = load_flow_execution(s_dir)
        if flow is None or flow.run_id is None:
            raise CorruptStateError(
                "Implementation phase requires a bound FlowExecution with run_id; "
                "the pipeline_engine must persist it before invoking the QA-subflow.",
                detail={"story_id": ctx.story_id, "story_dir": str(s_dir)},
            )
        # AG3-144 (FK-91 §91.1a Rule 15, no-lease-no-write): capture the
        # ownership-lease snapshot as early as feasible in this (possibly
        # long) QA-subflow execution -- mirrors the control-plane's own
        # admission snapshot (AG3-142). Threaded into the QA-layer/decision
        # persistence calls below, which re-verify it AT COMMIT TIME, in the
        # SAME transaction, under SELECT ... FOR UPDATE (no TOCTOU). ``None``
        # on the narrow SQLite unit-test path (K5 Postgres-only; no fence
        # mirroring there) -- the placeholder values are explicitly ignored
        # by the sqlite_store driver functions.
        ownership_fence = resolve_ownership_fence_snapshot(ctx.project_key, ctx.story_id)
        owner_session_id, expected_ownership_epoch = (
            ownership_fence if ownership_fence is not None else ("sqlite-unfenced", 0)
        )
        # AG3-026 Re-Review: VerifySystem.create_default() requires an
        # ArtifactManager (mandatory arg, fail-closed). Build via the
        # Composition-Root which already wires the manager to the story DB.
        # AG3-052 E1: this is the ONE productive lifecycle anchor of the
        # SonarQube-Green-Gate (the QA-subflow). When the run's config has
        # ``sonarqube.available == true`` we MUST wire the productive port so
        # the gate actually runs; an absent/unreadable scan artefact then
        # fails closed (APPLICABLE, attestation=None) — never silently absent
        # (FK-33 §33.6.5). ``available == false``/no-stanza/fast/non-code keep
        # the absent default port (declared skip).
        from agentkit.backend.bootstrap.composition_root import build_verify_system

        sonar_gate_port = _resolve_sonar_gate_port(ctx, s_dir)
        # E3 (AG3-041): the RemediationLoopController is the HARD owner of the
        # round ceiling. The handler reaches max_feedback_rounds from its config
        # into the VerifySystem (controller); it no longer re-derives its own
        # qa_rounds >= max escalation. NO ERROR BYPASSING — the ceiling lives in
        # exactly one place (FK-38 / FK-27 §27.2.2).
        # FIX-6 (FK-24 §24.3.4): a fast story's QA-subflow degenerates to the
        # hard tests-green floor. Wire the SAME real AG3-056 Build/Test capability
        # the closure Sanity-Gate uses; when CI is declared absent the runner is
        # ``None`` and the fast floor fails closed (non-disableable).
        # FIX-1 (AG3-042): wire the REAL Layer-1 build/test evidence port + the
        # real ARE provider from the per-run config (the project ``ci`` stanza /
        # ``features.are`` / the ARE client) so ``build.compile`` /
        # ``build.test_execution`` evaluate REAL CI results and ``are.gate``
        # activates IFF ``features.are``. Absent/declared-off config keeps the
        # fail-closed default ports (build/test BLOCKING fail, ARE not planned) —
        # never a fabricated green, never a silent ARE disable.
        build_test_port, are_provider = _resolve_structural_evidence_ports(ctx, s_dir)
        # ERROR 4 fix (AG3-063 remediation 2): pass the per-run ConformanceConfig
        # so ConformanceService.check_fidelity() uses configured thresholds from
        # project_config.pipeline.conformance (FK-32 §32.4b.3) instead of the
        # built-in defaults. The same load_project_config pattern already used by
        # _resolve_sonar_gate_port / _resolve_structural_evidence_ports above.
        conformance_config = _resolve_conformance_config(ctx)
        layer2_bundle_token_limit = _resolve_layer2_bundle_token_limit(ctx)
        verify_system = self._config.verify_system or build_verify_system(
            s_dir,
            sonar_gate_port=sonar_gate_port,
            max_feedback_rounds=self._config.max_feedback_rounds,
            fast_test_runner=_resolve_fast_test_runner(ctx),
            structural_build_test_port=build_test_port,
            structural_are_provider=are_provider,
            conformance_config=conformance_config,
            layer2_bundle_token_limit=layer2_bundle_token_limit,
            # AG3-067 AC7: thread the composition-root-injected Layer-2 transport
            # so the productive QA-subflow Layer-2 reviewers use the SAME client
            # the closure level-4 feedback port receives (single source of truth;
            # ``None`` => fail-closed FailClosedLlmClient inside build_verify_system).
            layer2_llm_client=self._config.layer2_llm_client,
        )

        # W2: Build PhaseEnvelopeView from envelope.state.payload (round 0
        # identities; refreshed from the persisted identities each round).
        phase_envelope_view = _build_phase_envelope_view(envelope)

        qa_rounds = state.memory.implementation.qa_feedback_rounds
        current_context = _verify_context_for(qa_rounds)
        previous_findings: tuple[Finding, ...] = ()
        attempt_nr = qa_rounds + 1

        # AG3-044 Orchestrator-Trennlinie (FK-20 §20.5.1): NO inline while-True.
        # The QA-subflow runs ONCE per on_enter. The subflow-internal remediation
        # loop is the orchestrator's job: on a FAIL below the ceiling the handler
        # sets agents_to_spawn=[remediation_worker] and returns control (the
        # engine re-yields, no phase change); on escalation it returns ESCALATED.
        # E1: run_qa_subflow is the ONLY ArtifactEnvelope write path and the ONLY
        # layer-execution path; its outcome carries the full VerifyDecision AND
        # the resolved QA-cycle identities (FK-27 §27.2.1).
        ctx_bundle = VerifyContextBundle(
            run_id=flow.run_id,
            story_dir=s_dir,
            phase_envelope=phase_envelope_view,
            attempt=attempt_nr,
            project_root=ctx.project_root,
        )
        target = ArtifactReference(
            artifact_class=ArtifactClass.WORKER,
            story_id=ctx.story_id,
            run_id=flow.run_id,
            record_key=f"envelopes/worker/{ctx.story_id}/{attempt_nr}",
        )
        # AG3-144 (Codex round-2): bind the SAME early-captured lease snapshot
        # for the ENTIRE mutating QA-subflow execution -- every artifact_envelopes
        # write reachable from run_qa_subflow (verify_system's layer/policy
        # envelopes, prompt-runtime materialization, the adversarial sandbox +
        # adversarial.json, the ARE-gate audit) and the qa_check_outcomes writes
        # below are fenced against THIS bound scope at their own Postgres commit,
        # regardless of how many BC-internal layers separate them from this
        # handler (no per-call parameter threading through those unrelated
        # public contracts -- FIX THE MODEL, ONE fence mechanism).
        with bind_ownership_fence_scope(
            project_key=ctx.project_key,
            story_id=ctx.story_id,
            run_id=flow.run_id,
            owner_session_id=owner_session_id,
            expected_ownership_epoch=expected_ownership_epoch,
        ):
            outcome: _QaSubflowOutcome = verify_system.run_qa_subflow(
                ctx_bundle,
                ctx.story_id,
                current_context,
                target,
                previous_findings=previous_findings,
            )
            # E1: Artifact names come from FK-27 §27.7 (deterministic).
            artifacts = list(ALL_QA_ARTIFACT_FILES)

            # E1: persist ALL FOUR QA-cycle identities resolved by the subflow into
            # the PhaseState payload (FK-27 §27.2.1 "persisted in the story state").
            awaiting_state = _state_with_payload(
                state,
                QaCycleStatus.AWAITING_QA,
                current_context,
                qa_feedback_rounds=qa_rounds,
                qa_cycle_round=outcome.qa_cycle_round,
                qa_cycle_id=outcome.qa_cycle_id,
                evidence_epoch=outcome.evidence_epoch,
                evidence_fingerprint=outcome.evidence_fingerprint,
            )

            # FK-69 path: feed decision from outcome (no second layer run).
            decision = outcome.decision
            projection_dir = resolve_qa_story_dir(
                s_dir,
                story_id=ctx.story_id,
                project_root=ctx.project_root,
            )
            # FK-69 §69.4 / AG3-035 #5: QA-Read-Models are persisted via the
            # ProjectionAccessor as the domain write boundary (not directly via the
            # state_backend facade). The atomic driver transaction stays encapsulated
            # in the injected batch port (finding D option i).
            from agentkit.backend.bootstrap.composition_root import build_projection_accessor
            from agentkit.backend.verify_system.check_outcome_emitter import CheckOutcomeEmitter

            accessor = build_projection_accessor(s_dir)
            accessor.record_qa_layer_artifacts(
                s_dir,
                layer_results=decision.layer_results,
                attempt_nr=attempt_nr,
                owner_session_id=owner_session_id,
                expected_ownership_epoch=expected_ownership_epoch,
                projection_dir=projection_dir,
            )
            # AG3-108 AC2/AC4: wire CheckOutcomeEmitter into the real QA persistence path.
            # Emits one qa_check_outcomes row per executed check per layer (triggered /
            # clean / overridden). The emitter is a verify-system BC producer; the
            # accessor is the DB owner (FK-69 §69.15).
            # AC4: load persisted OverrideRecords once (fail-closed: load_override_records
            # raises on backend errors — no silent swallow) and pass them into every
            # per-layer emit call so the emitter can mark `overridden` for any check_id
            # that matches an active override (FK-69 §69.11 rule 3 / §69.15.6 rule 5).
            # AG3-078 ERROR 1: build per-check check_id -> origin_check_ref mapping from
            # the stage registry (FK-33 §33.2.1). FC-derived stages carry CHK-NNNN in
            # StageDefinition.origin_check_ref; native stages carry None. A single layer
            # may mix both, so the mapping must be per-check_id (not per-layer).
            _stage_origin_map: dict[str, str | None] = {
                stage.stage_id: stage.origin_check_ref
                for stage in verify_system.stage_registry.stages
            }
            _override_records = load_override_records(s_dir)
            _emitter = CheckOutcomeEmitter()
            for layer_result in decision.layer_results:
                _emitter.emit(
                    flow,
                    layer_result,
                    attempt_no=attempt_nr,
                    override_records=_override_records,
                    projection_accessor=accessor,
                    check_origin_refs=_stage_origin_map,
                )
            record_verify_decision(
                s_dir,
                decision=decision,
                attempt_nr=attempt_nr,
                owner_session_id=owner_session_id,
                expected_ownership_epoch=expected_ownership_epoch,
                projection_dir=projection_dir,
            )

        if decision.passed:
            logger.info("QA-subflow passed for %s", ctx.story_id)
            save_story_context(s_dir, _implementation_completed_context(ctx))
            return HandlerResult(
                status=PhaseStatus.COMPLETED,
                artifacts_produced=tuple(dict.fromkeys(artifacts)),
                updated_state=_state_with_payload(
                    awaiting_state,
                    QaCycleStatus.PASS,
                    current_context,
                    qa_feedback_rounds=qa_rounds,
                    qa_cycle_round=outcome.qa_cycle_round,
                    qa_cycle_id=outcome.qa_cycle_id,
                    evidence_epoch=outcome.evidence_epoch,
                    evidence_fingerprint=outcome.evidence_fingerprint,
                ),
            )

        # E3: escalation is OWNED by the RemediationLoopController inside the
        # subflow; the handler consumes outcome.escalated verbatim (no duplicated
        # qa_rounds >= max check). FK-27 §27.2.2 max_rounds_exceeded -> ESCALATE.
        if outcome.escalated:
            error_msgs = _feedback_errors(outcome)
            escalated_state = _state_with_payload(
                awaiting_state,
                QaCycleStatus.ESCALATED,
                current_context,
                qa_feedback_rounds=qa_rounds,
                qa_cycle_round=outcome.qa_cycle_round,
                qa_cycle_id=outcome.qa_cycle_id,
                evidence_epoch=outcome.evidence_epoch,
                evidence_fingerprint=outcome.evidence_fingerprint,
            )
            if _is_implementation_required_after_exploration(outcome):
                escalated_state = evolve_phase_state(
                    escalated_state,
                    status=PhaseStatus.ESCALATED,
                    escalation_reason=(
                        EscalationReason.IMPLEMENTATION_REQUIRED_AFTER_EXPLORATION
                    ),
                )
            logger.warning(
                "QA-subflow escalated for %s after %d rounds",
                ctx.story_id,
                outcome.qa_cycle_round,
            )
            return HandlerResult(
                status=PhaseStatus.ESCALATED,
                errors=tuple(error_msgs),
                artifacts_produced=tuple(dict.fromkeys(artifacts)),
                updated_state=escalated_state,
            )

        # CONTINUE_REMEDIATION (FAIL below the ceiling): orchestrator-trennlinie.
        # Set agents_to_spawn=[remediation_worker] and return IN_PROGRESS so the
        # orchestrator spawns a remediation worker (SpawnReason.REMEDIATION) and
        # re-invokes the phase — a subflow-internal iteration, NOT a phase change
        # (FK-20 §20.5.1). The persisted qa_feedback_rounds is incremented for
        # the next round; carry this round's findings forward (FK-34).
        next_rounds = qa_rounds + 1
        remediation_state = _state_with_payload(
            awaiting_state,
            QaCycleStatus.AWAITING_REMEDIATION,
            QaContext.IMPLEMENTATION_REMEDIATION,
            qa_feedback_rounds=next_rounds,
            qa_cycle_round=outcome.qa_cycle_round,
            qa_cycle_id=outcome.qa_cycle_id,
            evidence_epoch=outcome.evidence_epoch,
            evidence_fingerprint=outcome.evidence_fingerprint,
        )
        # AG3-044 (FK-27 §27.6 / FK-48 §48.2): carry the Layer-3 adversarial
        # spawn orders the QA-subflow derived from this round's BLOCKING Layer-2
        # findings ALONGSIDE the remediation worker order. Both are typed
        # ``SpawnRequest`` entries in the SINGLE ``agents_to_spawn`` truth
        # (FK-45 §45.3); the orchestrator spawns the adversarial worker (writing
        # into the protected sandbox already materialised by the subflow) plus
        # the remediation worker on phase re-entry. No dead path.
        remediation_state = remediation_state.model_copy(
            update={
                "agents_to_spawn": [
                    SpawnRequest(
                        kind=SpawnKind.WORKER,
                        spawn_reason=SpawnReason.REMEDIATION,
                        target_id=ctx.story_id,
                    ),
                    *outcome.adversarial_spawn,
                ],
            },
        )
        logger.info(
            "QA-subflow FAIL below ceiling for %s -> remediation spawn (round %d)",
            ctx.story_id,
            next_rounds,
        )
        return HandlerResult(
            status=PhaseStatus.IN_PROGRESS,
            yield_status="awaiting_remediation",
            errors=tuple(_feedback_errors(outcome)),
            artifacts_produced=tuple(dict.fromkeys(artifacts)),
            updated_state=remediation_state,
        )

    def on_exit(self, _ctx: StoryContext, _envelope: PhaseEnvelope) -> None:
        """No-op for implementation phase."""

    def on_resume(
        self,
        ctx: StoryContext,
        envelope: PhaseEnvelope,
        trigger: str,
    ) -> HandlerResult:
        """Resume the implementation QA-subflow."""

        del trigger
        return self.on_enter(ctx, envelope)

    def _blocked_exit_result(
        self,
        state: PhaseState,
        story_dir: Path,
    ) -> HandlerResult | None:
        """BLOCKED-exit gate (FK-26 §26.11.2): read worker-manifest.json FIRST.

        Reads ``worker-manifest.json`` from the story dir BEFORE any QA-subflow
        (NO ERROR BYPASSING -- this is the unconditional first action). On
        ``status == BLOCKED`` returns ``PhaseStatus.ESCALATED`` with the blocker
        details (``blocking_issue`` / ``blocking_category`` /
        ``recommended_next_action``) carried in the TYPED
        ``HandlerResult.suggested_reaction`` field (AG3-044 AC6, FK-26 §26.11.2)
        -- not smuggled through ``errors[0]``. ``errors`` carries only a plain
        human summary line. The QA-subflow is NEVER started in that case
        (invariant ``worker_blocked_escalates``).

        A missing/unreadable/non-BLOCKED manifest returns ``None`` (the normal
        QA-subflow path proceeds). A manifest present but schema-invalid is a
        hard error (fail-closed) -- a worker exit is never silently ignored.

        Args:
            state: The current phase state.
            story_dir: The story working directory.

        Returns:
            A BLOCKED ``HandlerResult.ESCALATED`` when the manifest declares
            BLOCKED; ``None`` otherwise.

        Raises:
            CorruptStateError: When ``worker-manifest.json`` exists but is not
                valid JSON / not a valid WorkerManifest (fail-closed).
        """
        manifest = _read_worker_manifest(story_dir)
        if manifest is None or manifest.status is not WorkerManifestStatus.BLOCKED:
            return None
        suggested_reaction = _blocked_suggested_reaction(manifest)
        logger.warning(
            "Worker BLOCKED for %s (%s) -> ESCALATED, NO QA-subflow",
            manifest.story_id,
            manifest.blocking_category,
        )
        # AG3-044 AC6 (FK-26 §26.11.2): the structured blocker details live in
        # the TYPED ``suggested_reaction`` field; ``errors`` carries only a plain
        # human summary (no structured JSON smuggled through errors[0]).
        category = (
            manifest.blocking_category.value
            if manifest.blocking_category is not None
            else "unknown"
        )
        human_summary = (
            f"Worker BLOCKED ({category}): {manifest.blocking_issue}"
        )
        return HandlerResult(
            status=PhaseStatus.ESCALATED,
            errors=(human_summary,),
            suggested_reaction=suggested_reaction,
            yield_status=None,
            updated_state=_state_with_payload(
                state,
                QaCycleStatus.ESCALATED,
                QaContext.IMPLEMENTATION_INITIAL,
            ),
        )


def _resolve_sonar_gate_port(
    ctx: StoryContext, story_dir: Path
) -> SonarGateInputPort | None:
    """Resolve the productive ``sonarqube_gate`` port for this run (AG3-052 E1).

    Loads the project's ``sonarqube`` config from ``ctx.project_root`` and
    delegates to ``build_sonar_gate_port_for_run`` (FK-33 §33.6.5):

    * ``available == true`` AND ``mode != fast`` AND a code-producing story
      => the productive :class:`ConfiguredSonarGateInputPort`, or a
      fail-closed APPLICABLE port (``attestation = None``) when the per-run
      scan coordinates are missing/unreadable — NEVER a silent absent skip.
    * ``mode == fast`` => a port that genuinely resolves
      ``NOT_APPLICABLE_FAST`` (E2): the stage drops at the anchor, runtime
      distinguishable from ``available == false``/UNAVAILABLE.
    * ``available == false`` / no stanza on a non-code-producing project /
      non-code-producing story => ``None`` so the caller wires the absent
      default port (declared, deliberate skip => SKIP).

    FAIL-CLOSED (AG3-052 E1, FK-33 §33.6.5, ZERO DEBT): a config that cannot
    be loaded or validated for an ``available``-bearing run must NOT collapse
    into a silent absent skip. A ``ConfigError``/``ValueError`` from
    ``load_project_config`` PROPAGATES and stops the QA-subflow fail-closed —
    it is NOT swallowed into ``None``. The absent-port path is reachable ONLY
    when the config loads successfully and resolves to a deliberate
    non-applicability (``available: false`` / fast / non-code-producing).

    When ``ctx.project_root`` is unset, no project config exists to load for
    this run, so there is no Sonar stanza at all (``None`` => absent default).
    A code-producing project that reaches this anchor always has a loadable,
    explicit stanza (the E6 config-load rule forbids omission).

    Args:
        ctx: The run's :class:`StoryContext`.
        story_dir: The story working directory.

    Returns:
        A ``SonarGateInputPort`` (productive, fail-closed APPLICABLE, or a
        genuine NOT_APPLICABLE_FAST port), or ``None`` when Sonar is
        deliberately not applicable by config/story.

    Raises:
        ConfigError: When the project config cannot be loaded/validated.
            Propagated fail-closed (never downgraded to a silent skip).
    """
    if ctx.project_root is None:
        return None
    from agentkit.backend.config.loader import load_project_config
    from agentkit.backend.verify_system.sonarqube_gate.runtime_wiring import (
        build_sonar_gate_port_for_run,
    )

    # FAIL-CLOSED (E1): NO try/except ConfigError -> None. An unloadable or
    # invalid run-config (including the E6 hard-fail on an omitted stanza for a
    # code-producing project) MUST propagate and stop the QA-subflow, never
    # silently become an inert absent skip (FK-33 §33.6.5).
    project_config = load_project_config(ctx.project_root)
    return build_sonar_gate_port_for_run(
        project_config.pipeline.sonarqube, ctx, story_dir
    )


def _resolve_fast_test_runner(
    ctx: StoryContext,
) -> Callable[[Path], tuple[bool, str | None]] | None:
    """Resolve the fast-mode tests-green floor runner (FIX-6, FK-24 §24.3.4).

    Only a ``fast`` story degenerates to the tests-green floor; for every other
    mode the runner is irrelevant (the full QA layers run) so ``None`` is
    returned. For a fast story the SAME real AG3-056 Build/Test capability the
    closure Sanity-Gate uses is built from the project ``ci`` config via the
    composition root (:func:`build_fast_test_runner`). A DECLARED-absent CI yields
    ``None`` -> the fast floor is unconfirmable and the QA-subflow fails closed
    (the non-disableable floor, NO ERROR BYPASSING). An APPLICABLE-but-unreachable
    CI raises fail-closed inside the builder.

    Args:
        ctx: The run :class:`StoryContext`.

    Returns:
        The fast tests-green runner, or ``None`` (non-fast / declared-absent CI).

    Raises:
        ConfigError: When a fast story's project config cannot be loaded.
    """
    from agentkit.backend.story_context_manager.story_model import WireStoryMode

    if ctx.mode is not WireStoryMode.FAST or ctx.project_root is None:
        return None
    from agentkit.backend.bootstrap.composition_root import build_fast_test_runner
    from agentkit.backend.config.loader import load_project_config

    project_config = load_project_config(ctx.project_root)
    pipeline = getattr(project_config, "pipeline", None)
    ci_config = getattr(pipeline, "ci", None) if pipeline is not None else None
    return build_fast_test_runner(ci_config)


def _resolve_structural_evidence_ports(
    ctx: StoryContext,
    story_dir: Path,
) -> tuple[BuildTestEvidencePort | None, AreGateProvider | None]:
    """Resolve the REAL Layer-1 build/test + ARE ports for this run (FIX-1).

    The per-run caller owns the project-config read (the project ``ci`` stanza /
    ``features.are`` / the ARE client). It then asks the composition root to wire
    the REAL ports:

    * ``build.compile`` / ``build.test_execution`` evaluate REAL CI results via
      the AG3-056 commit-bound Build/Test runner (fail-closed absent default when
      CI is declared absent -- never a fabricated green).
    * ``are.gate`` activates IFF ``features.are == true`` via the real
      ``RequirementsCoverage`` provider (never silently disabled).

    Without a resolvable project root (e.g. a standalone test run) ``(None,
    None)`` keeps the fail-closed default ports.

    Args:
        ctx: The run :class:`StoryContext`.
        story_dir: The story working directory (git HEAD/diff source).

    Returns:
        ``(build_test_port, are_provider)`` -- either may be ``None`` (keep the
        fail-closed default).

    Raises:
        ConfigError: When the project config cannot be loaded for a run with a
            resolvable project root (propagated fail-closed, never a silent skip).
    """
    if ctx.project_root is None:
        return (None, None)
    from agentkit.backend.bootstrap.composition_root import (
        build_are_client_from_project_config,
        build_structural_are_provider,
        build_structural_build_test_port,
    )
    from agentkit.backend.config.loader import load_project_config

    project_config = load_project_config(ctx.project_root)
    pipeline = getattr(project_config, "pipeline", None)
    ci_config = getattr(pipeline, "ci", None) if pipeline is not None else None
    build_test_port = build_structural_build_test_port(ci_config, story_dir)
    are_client = build_are_client_from_project_config(project_config)
    are_provider = (
        build_structural_are_provider(are_client, pipeline, store_dir=ctx.project_root)
        if pipeline is not None
        else None
    )
    return (build_test_port, are_provider)


def _resolve_conformance_config(
    ctx: StoryContext,
) -> ConformanceConfig | None:
    """Resolve the FK-32 §32.4b.3 conformance thresholds for this run.

    Loads the project's ``pipeline.conformance`` stanza from
    ``ctx.project_root`` (the same ``load_project_config`` call already used
    by :func:`_resolve_sonar_gate_port` and
    :func:`_resolve_structural_evidence_ports`). Returns ``None`` when no
    project root is available so the ConformanceService falls back to its
    built-in defaults (50 KB / 500 KB).

    When a project root IS present the loaded ``ConformanceConfig`` always
    carries the fully-validated stanza — even when the project YAML omits the
    ``conformance`` key the model supplies the defaults. Propagation of
    ``ConfigError`` / ``ValueError`` from ``load_project_config`` is
    deliberate (fail-closed, NO ERROR BYPASSING).

    Args:
        ctx: The run :class:`StoryContext` carrying ``project_root``.

    Returns:
        The per-run ``ConformanceConfig`` from the project pipeline config,
        or ``None`` when ``ctx.project_root`` is unset.

    Raises:
        ConfigError: When the project config cannot be loaded.  Propagated
            fail-closed (never downgraded to a silent ``None``).
    """
    if ctx.project_root is None:
        return None
    from agentkit.backend.config.loader import load_project_config

    project_config = load_project_config(ctx.project_root)
    pipeline = getattr(project_config, "pipeline", None)
    if pipeline is None:
        return None
    return getattr(pipeline, "conformance", None)


def _resolve_layer2_bundle_token_limit(ctx: StoryContext) -> int:
    """Resolve ``pipeline.layer2.bundle_token_limit`` for Layer-2 packing."""
    if ctx.project_root is None:
        return 32_000
    from agentkit.backend.config.loader import load_project_config

    project_config = load_project_config(ctx.project_root)
    pipeline = getattr(project_config, "pipeline", None)
    layer2 = getattr(pipeline, "layer2", None) if pipeline is not None else None
    limit = getattr(layer2, "bundle_token_limit", 32_000)
    return int(limit)


def _build_phase_envelope_view(envelope: PhaseEnvelope) -> PhaseEnvelopeView | None:
    """Build a ``PhaseEnvelopeView`` from a ``PhaseEnvelope``.

    W2 (AG3-026 Re-Review): isolates the ``pipeline_engine``-type
    ``PhaseEnvelope`` from the ``verify_system`` BC.

    Args:
        envelope: The ``PhaseEnvelope`` from the handler context.

    Returns:
        ``PhaseEnvelopeView`` with the four QA-cycle fields, or ``None`` if no
        valid ``ImplementationPayload`` with an active cycle is present.
    """
    return _build_phase_envelope_view_from_state(envelope.state)


def _build_phase_envelope_view_from_state(
    state: PhaseState,
) -> PhaseEnvelopeView | None:
    """Build a ``PhaseEnvelopeView`` from a ``PhaseState`` payload.

    E1 (AG3-041): used both for the round-0 view (from the persisted envelope)
    AND to REFRESH the view between remediation rounds from the just-persisted
    identities, so the next round's subflow sees the active cycle and advances
    it (``advance_qa_cycle``) rather than starting a fresh one.

    Args:
        state: The ``PhaseState`` carrying the ``ImplementationPayload``.

    Returns:
        ``PhaseEnvelopeView`` with the four QA-cycle fields, or ``None`` when
        the payload is not an ``ImplementationPayload`` or no cycle is active.
    """
    from agentkit.backend.pipeline_engine.phase_executor import ImplementationPayload

    payload = state.payload
    if not isinstance(payload, ImplementationPayload):
        return None
    # Only create a view when an active cycle exists (qa_cycle_id set).
    if payload.qa_cycle_id is None:
        return None
    return PhaseEnvelopeView(
        qa_cycle_id=payload.qa_cycle_id,
        qa_cycle_round=payload.qa_cycle_round if payload.qa_cycle_round >= 1 else None,
        evidence_epoch=payload.evidence_epoch,
        evidence_fingerprint=payload.evidence_fingerprint,
    )


def _verify_context_for(qa_feedback_rounds: int) -> QaContext:
    if qa_feedback_rounds == 0:
        return QaContext.IMPLEMENTATION_INITIAL
    return QaContext.IMPLEMENTATION_REMEDIATION


#: Worker-manifest filename (FK-27 §27.4.1 / FK-26 §26.8). Same file the
#: Layer-1 ``artifact.worker_manifest`` check reads -- one source of truth.
_WORKER_MANIFEST_FILENAME = WORKER_MANIFEST_FILE


def _read_worker_manifest(story_dir: Path) -> WorkerManifest | None:
    """Read + parse ``worker-manifest.json`` from the story dir (fail-closed).

    Args:
        story_dir: The story working directory.

    Returns:
        The parsed :class:`WorkerManifest`, or ``None`` when the file is absent
        (no worker exit recorded yet -- the QA-subflow path proceeds).

    Raises:
        CorruptStateError: When the file exists but is not valid JSON / not a
            valid WorkerManifest. A present-but-invalid worker exit is a hard
            error, never silently ignored (CLAUDE.md FAIL-CLOSED).
    """
    path = story_dir / _WORKER_MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise CorruptStateError(
            f"{_WORKER_MANIFEST_FILENAME} is not valid JSON (FK-26 §26.8)",
            detail={"story_dir": str(story_dir), "error": str(exc)},
        ) from exc
    try:
        return WorkerManifest.model_validate(raw)
    except ValueError as exc:
        raise CorruptStateError(
            f"{_WORKER_MANIFEST_FILENAME} is not a valid WorkerManifest "
            "(FK-26 §26.8.2)",
            detail={"story_dir": str(story_dir), "error": str(exc)},
        ) from exc


def _blocked_suggested_reaction(manifest: WorkerManifest) -> str:
    """Build the ESCALATED ``suggested_reaction`` from a BLOCKED manifest.

    FK-26 §26.11.2: the ``suggested_reaction`` carries the blocker details
    (``blocking_issue`` / ``blocking_category`` / ``recommended_next_action``)
    so the orchestrator can react. The BLOCKED required-field validator
    guarantees all three are present (fail-closed).

    Args:
        manifest: The BLOCKED worker manifest.

    Returns:
        A serialized ``suggested_reaction`` JSON string (FK-26 §26.11.2 shape).
    """
    payload = {
        "action": (
            "Worker blocked by external constraint. Review blocker details "
            "and resolve before re-running."
        ),
        "blocking_issue": manifest.blocking_issue,
        "blocking_category": (
            manifest.blocking_category.value
            if manifest.blocking_category is not None
            else None
        ),
        "recommended_next_action": manifest.recommended_next_action,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _feedback_errors(outcome: _QaSubflowOutcome) -> list[str]:
    """Build human-readable error strings from a failed QA-subflow outcome.

    Args:
        outcome: The ``QaSubflowOutcome`` from a failed QA-subflow run.

    Returns:
        List of error message strings for ``HandlerResult.errors``.
    """
    decision = outcome.decision
    feedback = outcome.feedback
    errors = [str(decision.summary)]
    if feedback is not None:
        errors.append(str(feedback.to_prompt_text()))
    return errors


def _is_implementation_required_after_exploration(outcome: _QaSubflowOutcome) -> bool:
    """Whether the QA-subflow failed at the FK-24 terminality precondition."""
    return any(
        finding.check == "implementation_evidence.required_after_exploration"
        for finding in outcome.decision.all_findings
    )


def _implementation_completed_context(ctx: StoryContext) -> StoryContext:
    """Return ``StoryContext`` with implementation follow-up flags resolved."""
    from agentkit.backend.story_context_manager.types import StoryType

    if ctx.story_type not in (StoryType.IMPLEMENTATION, StoryType.BUGFIX):
        return ctx
    return ctx.model_copy(
        update={
            "implementation_required": False,
            "closure_allowed": True,
            "story_done": False,
            "execution_pending": False,
        }
    )


def _state_with_payload(
    state: PhaseState,
    qa_cycle_status: QaCycleStatus,
    verify_context: QaContext,
    *,
    qa_feedback_rounds: int | None = None,
    qa_cycle_round: int = 0,
    qa_cycle_id: str | None = None,
    evidence_epoch: datetime | None = None,
    evidence_fingerprint: str | None = None,
) -> PhaseState:
    """Rebuild the implementation ``PhaseState`` with QA-cycle identities.

    E1 (AG3-041): the phase handler is the State-Owner; it persists ALL FOUR
    QA-cycle identity fields (``qa_cycle_id``, ``qa_cycle_round``,
    ``evidence_epoch``, ``evidence_fingerprint``) into ``ImplementationPayload``
    so the cycle identity is durable in the Story-State (FK-27 §27.2.1), not
    just the round.

    Args:
        state: The source ``PhaseState`` to derive from.
        qa_cycle_status: The QA-cycle status to set (FK-27 §27.2.2).
        verify_context: The subflow verify context (initial vs remediation).
        qa_feedback_rounds: When set, rebuilds ``PhaseMemory`` with this
            carry-forward counter; ``None`` keeps the existing memory.
        qa_cycle_round: Monotonic QA-cycle round to persist.
        qa_cycle_id: 12-char hex cycle id resolved by the subflow.
        evidence_epoch: UTC-aware timestamp of the cycle's last mutation.
        evidence_fingerprint: SHA-256 hex over the cycle's evidence.

    Returns:
        A new ``PhaseState`` carrying the persisted QA-cycle identities.
    """
    memory = state.memory
    if qa_feedback_rounds is not None:
        memory = PhaseMemory(
            exploration=state.memory.exploration,
            implementation=ImplementationPhaseMemory(
                qa_feedback_rounds=qa_feedback_rounds,
            ),
        )
    return evolve_phase_state(
        state,
        phase="implementation",
        status=state.status,
        payload=ImplementationPayload(
            qa_cycle_status=qa_cycle_status,
            verify_context=verify_context,
            qa_cycle_round=qa_cycle_round,
            qa_cycle_id=qa_cycle_id,
            evidence_epoch=evidence_epoch,
            evidence_fingerprint=evidence_fingerprint,
        ),
        memory=memory,
        pause_reason=state.pause_reason,
        escalation_reason=state.escalation_reason,
        review_round=state.review_round,
        errors=list(state.errors),
        attempt_id=state.attempt_id,
    )


def _check_is_implementation_approval(
    ctx: StoryContext,
    s_dir: Path,
    state: PhaseState,
) -> HandlerResult | None:
    """AG3-069 (FK-05 §5.5.1/§5.5.4/§5.6, AC2): IS binding-integrity pre-check.

    For integration_stabilization stories, the implementation phase / worker
    spawn must not proceed without an APPROVED + BOUND IntegrationScopeManifest.
    This is the real production wiring of the §2.3 worker-spawn enforcement point:

    1. ``check_approval_present`` -- a ManifestApprovalRecord MUST exist;
    2. ``check_binding_integrity`` -- the record MUST bind the active manifest
       (hash + version + project_key + story_id + run_id all match). A
       hash/version/project/story/run mismatch BLOCKS fail-closed (AC2). The
       active run id is resolved from the bound FlowExecution (the same run the
       handler runs the QA-subflow under).

    Gated on the IS contract so standard stories are completely unaffected.

    Args:
        ctx: Story context (checked for IS contract).
        s_dir: Story working directory (manifest/approval/run source).
        state: Current phase state (for ESCALATED result).

    Returns:
        An ESCALATED ``HandlerResult`` when the IS contract has no approved or
        no bound manifest, else ``None``.
    """
    from agentkit.backend.story_context_manager.types import ImplementationContract

    if ctx.implementation_contract is not ImplementationContract.INTEGRATION_STABILIZATION:
        return None  # Standard stories: no IS approval check.

    from agentkit.backend.integration_stabilization.preconditions import (
        check_approval_present,
        check_binding_integrity,
    )
    from agentkit.backend.integration_stabilization.state import (
        load_integration_manifest,
        load_manifest_approval,
    )

    approval = load_manifest_approval(s_dir)
    if not check_approval_present(approval).approved:
        return _is_spawn_block(
            state,
            "no approved IntegrationScopeManifest found. The manifest must be "
            "produced and approved in the exploration phase before "
            "implementation may proceed (FK-05 §5.5.1/§5.6, AC2, invariant: "
            "integration_contract_requires_exploration_first).",
        )

    manifest = load_integration_manifest(s_dir)
    if manifest is None:
        return _is_spawn_block(
            state,
            "an approval record is present but no IntegrationScopeManifest was "
            "found; binding integrity cannot be verified (FK-05 §5.5.4, AC2).",
        )

    assert approval is not None  # noqa: S101 -- guaranteed by check_approval_present
    run_id = _resolve_is_run_id(s_dir, fallback=approval.run_id)
    binding = check_binding_integrity(manifest, approval, current_run_id=run_id)
    if not binding.binding_valid:
        return _is_spawn_block(
            state,
            "manifest-approval binding integrity failed: "
            f"{binding.reason} (FK-05 §5.5.4, AC2, invariant: binding_integrity).",
        )
    return None


def _resolve_is_run_id(s_dir: Path, *, fallback: str) -> str:
    """Resolve the active run id for the IS binding check (FlowExecution scope).

    The binding-integrity check must verify the approval is bound to the run the
    worker spawns under. The run id comes from the bound FlowExecution; an
    unresolvable scope falls back to the approval's own run id (the binding then
    compares the record against itself only if no run is bound -- still detects
    every other mismatch dimension).
    """
    flow = load_flow_execution(s_dir)
    if flow is not None and flow.run_id:
        return flow.run_id
    return fallback


def _is_spawn_block(state: PhaseState, detail: str) -> HandlerResult:
    """Build the ESCALATED IS worker-spawn block result (fail-closed, AC2)."""
    return HandlerResult(
        status=PhaseStatus.ESCALATED,
        errors=(f"Integration-stabilization implementation blocked: {detail}",),
        updated_state=_state_with_payload(
            state,
            QaCycleStatus.ESCALATED,
            QaContext.IMPLEMENTATION_INITIAL,
        ),
    )
