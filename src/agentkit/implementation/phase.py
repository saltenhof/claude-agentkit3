"""Implementation phase handler with internal QA-subflow."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.bootstrap.composition_root import build_artifact_manager
from agentkit.core_types import QaContext
from agentkit.exceptions import CorruptStateError
from agentkit.implementation.qa_subflow import (
    QaSubflowCycle,
    QaSubflowCycleResult,
)
from agentkit.installer.paths import resolve_qa_story_dir
from agentkit.pipeline_engine.lifecycle import HandlerResult
from agentkit.state_backend.store import (
    load_flow_execution,
    record_layer_artifacts,
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
from agentkit.verify_system import VerifySystem
from agentkit.verify_system.artifacts import (
    write_layer_artifacts,
    write_verify_decision_artifacts,
)
from agentkit.verify_system.llm_evaluator.reviewer import SemanticReviewer
from agentkit.verify_system.structural.checker import StructuralChecker

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.protocols import QALayer

logger = logging.getLogger(__name__)


@dataclass
class ImplementationConfig:
    """Configuration for the implementation phase handler."""

    story_dir: Path | None = None
    max_feedback_rounds: int = 3
    layers: list[QALayer] = field(default_factory=list)
    verify_system: VerifySystem | None = None


class ImplementationPhaseHandler:
    """Run implementation and its internal QA-subflow."""

    def __init__(self, config: ImplementationConfig) -> None:
        self._config = config

    def on_enter(self, ctx: StoryContext, envelope: PhaseEnvelope) -> HandlerResult:
        """Run the implementation QA-subflow to pass or escalation."""

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
        manager = build_artifact_manager(s_dir)

        verify_system = self._config.verify_system or VerifySystem.create_default()
        layers: list[QALayer] = list(self._config.layers) if self._config.layers else [
            StructuralChecker(),
            SemanticReviewer(),
            verify_system.adversarial_layer(),
        ]
        cycle = QaSubflowCycle(layers=layers, verify_system=verify_system)
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
            result = cycle.run(ctx, s_dir, attempt_nr=attempt_nr)
            projection_dir = resolve_qa_story_dir(
                s_dir,
                story_id=ctx.story_id,
                project_root=ctx.project_root,
            )
            # Schreibpfad 1: ArtifactEnvelope-Wahrheit via ArtifactManager
            #   (verify_system kennt ausschliesslich diese API).
            artifacts.extend(
                write_layer_artifacts(
                    manager=manager,
                    story_id=ctx.story_id,
                    run_id=flow.run_id,
                    layer_results=result.decision.layer_results,
                    attempt_nr=result.attempt_nr,
                ),
            )
            artifacts.extend(
                write_verify_decision_artifacts(
                    manager=manager,
                    story_id=ctx.story_id,
                    run_id=flow.run_id,
                    decision=result.decision,
                    attempt_nr=result.attempt_nr,
                ),
            )
            # Schreibpfad 2: FK-69-Materialisierung (qa_stage_results,
            #   qa_findings, decision_records) + Projektionsdatei via
            #   state_backend. Beide Pfade sind idempotent (UPSERT) und
            #   konvergieren bei Re-Run auf den aktuellen Stand.
            record_layer_artifacts(
                s_dir,
                layer_results=result.decision.layer_results,
                attempt_nr=result.attempt_nr,
                projection_dir=projection_dir,
            )
            record_verify_decision(
                s_dir,
                decision=result.decision,
                attempt_nr=result.attempt_nr,
                projection_dir=projection_dir,
            )

            if result.decision.passed:
                logger.info("QA-subflow passed for %s", ctx.story_id)
                return HandlerResult(
                    status=PhaseStatus.COMPLETED,
                    artifacts_produced=tuple(artifacts),
                    updated_state=_state_with_payload(
                        awaiting_state,
                        QaCycleStatus.PASS,
                        current_context,
                        qa_feedback_rounds=qa_rounds,
                        qa_cycle_round=attempt_nr,
                    ),
                )

            if qa_rounds >= self._config.max_feedback_rounds:
                error_msgs = _feedback_errors(result)
                logger.warning(
                    "QA-subflow escalated for %s after %d rounds",
                    ctx.story_id,
                    qa_rounds,
                )
                return HandlerResult(
                    status=PhaseStatus.ESCALATED,
                    errors=tuple(error_msgs),
                    artifacts_produced=tuple(artifacts),
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


def _verify_context_for(qa_feedback_rounds: int) -> QaContext:
    if qa_feedback_rounds == 0:
        return QaContext.IMPLEMENTATION_INITIAL
    return QaContext.IMPLEMENTATION_REMEDIATION


def _feedback_errors(result: QaSubflowCycleResult) -> list[str]:
    decision = result.decision
    feedback = result.feedback
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
