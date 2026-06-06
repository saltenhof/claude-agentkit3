"""Implementation phase handler with internal QA-subflow.

E1 (AG3-026 Pass-2): ``on_enter`` calls
``verify_system.run_qa_subflow(ctx_bundle, story_id, qa_context, target)``
as the ONLY ArtifactEnvelope write path AND the ONLY layer-execution
path. ``run_qa_subflow`` now returns ``QaSubflowOutcome`` which carries
the full ``VerifyDecision``; the FK-69 path is fed directly from
``outcome.decision`` -- no second cycle run needed. QA-Read-Models are
written via ``ProjectionAccessor.record_qa_layer_artifacts`` (fachliche
Schreibgrenze, AG3-035 #5); ``record_verify_decision`` persists the decision.

W2 (AG3-026 Re-Review): ``ImplementationPhaseHandler`` builds a
``PhaseEnvelopeView`` from ``envelope.state.payload`` and passes it
into ``verify_system.run_qa_subflow``, avoiding a ``pipeline_engine``
import inside ``verify_system``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.artifacts import ArtifactReference
from agentkit.core_types import ArtifactClass, QaContext
from agentkit.core_types.qa_artifact_names import ALL_QA_ARTIFACT_FILES
from agentkit.exceptions import CorruptStateError
from agentkit.installer.paths import resolve_qa_story_dir
from agentkit.pipeline_engine.lifecycle import HandlerResult
from agentkit.state_backend.store import (
    load_flow_execution,
    record_verify_decision,
    save_story_context,
)
from agentkit.story_context_manager.models import (
    ImplementationPayload,
    ImplementationPhaseMemory,
    PhaseMemory,
    PhaseState,
    PhaseStatus,
    QaCycleStatus,
)
from agentkit.verify_system.contract import PhaseEnvelopeView, VerifyContextBundle
from agentkit.verify_system.contract import QaSubflowOutcome as _QaSubflowOutcome

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system import VerifySystem
    from agentkit.verify_system.protocols import Finding
    from agentkit.verify_system.sonarqube_gate.port import SonarGateInputPort

logger = logging.getLogger(__name__)


@dataclass
class ImplementationConfig:
    """Configuration for the implementation phase handler.

    Attributes:
        story_dir: Root directory of the story being verified.
        max_feedback_rounds: Maximum QA feedback rounds before escalation.
        verify_system: Optional pre-wired ``VerifySystem`` instance;
            if ``None``, built via ``composition_root.build_verify_system``.
    """

    story_dir: Path | None = None
    max_feedback_rounds: int = 3
    verify_system: VerifySystem | None = None


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
        save_story_context(s_dir, ctx)

        flow = load_flow_execution(s_dir)
        if flow is None or flow.run_id is None:
            raise CorruptStateError(
                "Implementation phase requires a bound FlowExecution with run_id; "
                "the pipeline_engine must persist it before invoking the QA-subflow.",
                detail={"story_id": ctx.story_id, "story_dir": str(s_dir)},
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
        from agentkit.bootstrap.composition_root import build_verify_system

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
        verify_system = self._config.verify_system or build_verify_system(
            s_dir,
            sonar_gate_port=sonar_gate_port,
            max_feedback_rounds=self._config.max_feedback_rounds,
            fast_test_runner=_resolve_fast_test_runner(ctx),
        )

        # W2: Build PhaseEnvelopeView from envelope.state.payload (round 0
        # identities; refreshed from the persisted identities each round).
        phase_envelope_view = _build_phase_envelope_view(envelope)

        qa_rounds = state.memory.implementation.qa_feedback_rounds
        current_context = _verify_context_for(qa_rounds)
        artifacts: list[str] = []
        previous_findings: tuple[Finding, ...] = ()

        while True:
            attempt_nr = qa_rounds + 1

            # E1: run_qa_subflow is the ONLY ArtifactEnvelope write path
            # and the ONLY layer-execution path. The returned
            # QaSubflowOutcome carries the full VerifyDecision AND the resolved
            # QA-cycle identities (qa_cycle_id, round, evidence_epoch,
            # fingerprint) — the state owner persists ALL four (FK-27 §27.2.1).
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
            outcome: _QaSubflowOutcome = verify_system.run_qa_subflow(
                ctx_bundle,
                ctx.story_id,
                current_context,
                target,
                previous_findings=previous_findings,
            )
            # E1: Artifact names come from FK-27 §27.7 (deterministic).
            artifacts.extend(ALL_QA_ARTIFACT_FILES)

            # E1: persist ALL FOUR QA-cycle identities resolved by the subflow
            # into the PhaseState payload (FK-27 §27.2.1 "im Story-State
            # persistiert"). awaiting_state carries the cycle so a crash between
            # the subflow and the terminal write keeps the identities durable.
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
            # Refresh the view from the persisted identities so the NEXT round's
            # subflow sees the active cycle (advance_qa_cycle, not start_cycle).
            phase_envelope_view = _build_phase_envelope_view_from_state(
                awaiting_state
            )

            # FK-69 path: feed decision from outcome (no second layer run).
            decision = outcome.decision
            projection_dir = resolve_qa_story_dir(
                s_dir,
                story_id=ctx.story_id,
                project_root=ctx.project_root,
            )
            # FK-69 §69.4 / AG3-035 #5: QA-Read-Models werden ueber den
            # ProjectionAccessor als fachliche Schreibgrenze persistiert (nicht
            # direkt via state_backend-Fassade). Die atomare Driver-Transaktion
            # bleibt im injizierten Batch-Port gekapselt (Befund D Option i).
            from agentkit.bootstrap.composition_root import build_projection_accessor

            accessor = build_projection_accessor(s_dir)
            accessor.record_qa_layer_artifacts(
                s_dir,
                layer_results=decision.layer_results,
                attempt_nr=attempt_nr,
                projection_dir=projection_dir,
            )
            record_verify_decision(
                s_dir,
                decision=decision,
                attempt_nr=attempt_nr,
                projection_dir=projection_dir,
            )

            if decision.passed:
                logger.info("QA-subflow passed for %s", ctx.story_id)
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
            # subflow; the handler consumes outcome.escalated verbatim (no
            # duplicated qa_rounds >= max check). FK-27 §27.2.2 max_rounds.
            if outcome.escalated:
                error_msgs = _feedback_errors(outcome)
                logger.warning(
                    "QA-subflow escalated for %s after %d rounds",
                    ctx.story_id,
                    outcome.qa_cycle_round,
                )
                return HandlerResult(
                    status=PhaseStatus.ESCALATED,
                    errors=tuple(error_msgs),
                    artifacts_produced=tuple(dict.fromkeys(artifacts)),
                    updated_state=_state_with_payload(
                        awaiting_state,
                        QaCycleStatus.ESCALATED,
                        current_context,
                        qa_feedback_rounds=qa_rounds,
                        qa_cycle_round=outcome.qa_cycle_round,
                        qa_cycle_id=outcome.qa_cycle_id,
                        evidence_epoch=outcome.evidence_epoch,
                        evidence_fingerprint=outcome.evidence_fingerprint,
                    ),
                )

            # FAIL below the ceiling -> next remediation round. Carry this
            # round's findings forward so the FindingResolutionAssessor can
            # classify them next round (FK-34, closure_blocked).
            previous_findings = decision.all_findings
            qa_rounds += 1
            current_context = QaContext.IMPLEMENTATION_REMEDIATION

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
    from agentkit.config.loader import load_project_config
    from agentkit.verify_system.sonarqube_gate.runtime_wiring import (
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
    from agentkit.story_context_manager.story_model import WireStoryMode

    if ctx.mode is not WireStoryMode.FAST or ctx.project_root is None:
        return None
    from agentkit.bootstrap.composition_root import build_fast_test_runner
    from agentkit.config.loader import load_project_config

    project_config = load_project_config(ctx.project_root)
    pipeline = getattr(project_config, "pipeline", None)
    ci_config = getattr(pipeline, "ci", None) if pipeline is not None else None
    return build_fast_test_runner(ci_config)


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
    from agentkit.story_context_manager.models import ImplementationPayload

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
    return PhaseState(
        story_id=state.story_id,
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
        paused_reason=state.paused_reason,
        review_round=state.review_round,
        errors=list(state.errors),
        attempt_id=state.attempt_id,
    )
