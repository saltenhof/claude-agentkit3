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
    from pathlib import Path

    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system import VerifySystem
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
        verify_system = self._config.verify_system or build_verify_system(
            s_dir, sonar_gate_port=sonar_gate_port
        )

        # W2: Build PhaseEnvelopeView from envelope.state.payload.
        phase_envelope_view = _build_phase_envelope_view(envelope)

        qa_rounds = state.memory.implementation.qa_feedback_rounds
        current_context = _verify_context_for(qa_rounds)
        artifacts: list[str] = []

        while True:
            attempt_nr = qa_rounds + 1
            awaiting_state = _state_with_payload(
                state,
                QaCycleStatus.AWAITING_QA,
                current_context,
                qa_feedback_rounds=qa_rounds,
                qa_cycle_round=attempt_nr,
            )

            # E1: run_qa_subflow is the ONLY ArtifactEnvelope write path
            # and the ONLY layer-execution path. The returned
            # QaSubflowOutcome carries the full VerifyDecision.
            ctx_bundle = VerifyContextBundle(
                run_id=flow.run_id,
                story_dir=s_dir,
                phase_envelope=phase_envelope_view,
                attempt=attempt_nr,
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
            )
            # E1: Artifact names come from FK-27 §27.7 (deterministic).
            artifacts.extend(ALL_QA_ARTIFACT_FILES)

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
                        qa_cycle_round=attempt_nr,
                    ),
                )

            if qa_rounds >= self._config.max_feedback_rounds:
                error_msgs = _feedback_errors(outcome)
                logger.warning(
                    "QA-subflow escalated for %s after %d rounds",
                    ctx.story_id,
                    qa_rounds,
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
                        qa_cycle_round=attempt_nr,
                    ),
                )

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


def _build_phase_envelope_view(envelope: PhaseEnvelope) -> PhaseEnvelopeView | None:
    """Build a ``PhaseEnvelopeView`` from a ``PhaseEnvelope``.

    Extracts only the four QA-cycle identity fields from
    ``envelope.state.payload`` (if it is an ``ImplementationPayload``).
    Returns ``None`` if the payload is not an ``ImplementationPayload``
    or the fields are all unset.

    W2 (AG3-026 Re-Review): isolates the ``pipeline_engine``-type
    ``PhaseEnvelope`` from the ``verify_system`` BC.

    Args:
        envelope: The ``PhaseEnvelope`` from the handler context.

    Returns:
        ``PhaseEnvelopeView`` with the four QA-cycle fields, or
        ``None`` if no valid ``ImplementationPayload`` is present.
    """
    from agentkit.story_context_manager.models import ImplementationPayload

    payload = envelope.state.payload
    if not isinstance(payload, ImplementationPayload):
        return None
    # Only create view if at least one QA-cycle field is set.
    if all(
        v is None
        for v in (
            payload.qa_cycle_id,
            payload.qa_cycle_round or None,
            payload.evidence_epoch,
            payload.evidence_fingerprint,
        )
    ):
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
) -> PhaseState:
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
        ),
        memory=memory,
        paused_reason=state.paused_reason,
        review_round=state.review_round,
        errors=list(state.errors),
        attempt_id=state.attempt_id,
    )
