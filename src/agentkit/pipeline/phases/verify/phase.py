"""Verify phase handler -- runs QA cycle and handles remediation.

Implements the :class:`~agentkit.pipeline.lifecycle.PhaseHandler`
protocol. Runs one ``VerifyCycle`` per invocation. The pipeline
engine decides whether to re-enter for remediation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.installer.paths import resolve_qa_story_dir
from agentkit.pipeline.lifecycle import HandlerResult
from agentkit.pipeline.phases.verify.cycle import VerifyCycle
from agentkit.qa.adversarial.challenger import AdversarialChallenger
from agentkit.qa.evaluators.reviewer import SemanticReviewer
from agentkit.qa.policy_engine.engine import PolicyEngine
from agentkit.qa.structural.checker import StructuralChecker
from agentkit.state_backend import (
    record_layer_artifacts,
    record_verify_decision,
    save_story_context,
)
from agentkit.story_context_manager.models import PhaseStatus

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.qa.protocols import QALayer
    from agentkit.story_context_manager.models import PhaseState, StoryContext

logger = logging.getLogger(__name__)


@dataclass
class VerifyConfig:
    """Configuration for the verify phase.

    Attributes:
        story_dir: Directory containing story artifacts. Required.
        max_feedback_rounds: Maximum remediation rounds before escalation.
        layers: Override default QA layers (for testing).
        policy_engine: Override default policy engine (for testing).
    """

    story_dir: Path | None = None
    max_feedback_rounds: int = 3
    layers: list[QALayer] = field(default_factory=list)
    policy_engine: PolicyEngine | None = None


class VerifyPhaseHandler:
    """Phase handler for the Verify phase.

    Runs one ``VerifyCycle``. Based on the result:

    - PASS or PASS_WITH_WARNINGS -> COMPLETED.
    - FAIL -> FAILED with feedback text in errors (the engine or
      orchestrator decides whether to invoke remediation).

    Implements the :class:`~agentkit.pipeline.lifecycle.PhaseHandler`
    protocol.
    """

    def __init__(self, config: VerifyConfig) -> None:
        self._config = config

    def on_enter(self, ctx: StoryContext, state: PhaseState) -> HandlerResult:
        """Run one verify cycle.

        Steps:
            1. Resolve story_dir from config.
            2. Build QA layers (default: structural + semantic +
               adversarial).
            3. Build policy engine.
            4. Run VerifyCycle.
            5. Return COMPLETED or FAILED based on decision.

        Args:
            ctx: The story context for this pipeline run.
            state: The current phase state.

        Returns:
            A ``HandlerResult`` describing the outcome.
        """
        s_dir = self._config.story_dir
        if s_dir is None:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=("story_dir is not configured in VerifyConfig",),
            )
        save_story_context(s_dir, ctx)

        # Build layers
        layers: list[QALayer] = list(self._config.layers) if self._config.layers else [
            StructuralChecker(),
            SemanticReviewer(),
            AdversarialChallenger(),
        ]

        # Build policy engine
        engine = self._config.policy_engine or PolicyEngine()

        # Run cycle
        attempt_nr = state.review_round + 1
        cycle = VerifyCycle(layers=layers, policy_engine=engine)
        result = cycle.run(ctx, s_dir, attempt_nr=attempt_nr)
        projection_dir = resolve_qa_story_dir(
            s_dir,
            story_id=ctx.story_id,
            project_root=ctx.project_root,
        )
        artifacts = record_layer_artifacts(
            s_dir,
            layer_results=result.decision.layer_results,
            attempt_nr=result.attempt_nr,
            projection_dir=projection_dir,
        )

        # Persist canonical verify decision plus projection artifacts.
        artifacts = (
            *artifacts,
            *record_verify_decision(
                s_dir,
                decision=result.decision,
                attempt_nr=result.attempt_nr,
                projection_dir=projection_dir,
            ),
        )

        if result.decision.passed:
            logger.info(
                "Verify passed for %s: %s",
                ctx.story_id, result.decision.status,
            )
            return HandlerResult(
                status=PhaseStatus.COMPLETED,
                artifacts_produced=artifacts,
            )

        # FAIL -- include feedback in errors
        error_msgs: list[str] = [result.decision.summary]
        if result.feedback is not None:
            error_msgs.append(result.feedback.to_prompt_text())

        logger.warning(
            "Verify failed for %s (attempt %d): %s",
            ctx.story_id, attempt_nr, result.decision.summary,
        )
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=tuple(error_msgs),
            artifacts_produced=artifacts,
        )

    def on_exit(self, ctx: StoryContext, state: PhaseState) -> None:
        """No-op for verify phase.

        Args:
            ctx: The story context (unused).
            state: The current phase state (unused).
        """

    def on_resume(
        self, ctx: StoryContext, state: PhaseState, trigger: str,
    ) -> HandlerResult:
        """Resume after remediation -- run another verify cycle.

        Simply re-runs ``on_enter`` to re-evaluate all layers.

        Args:
            ctx: The story context for this pipeline run.
            state: The current phase state.
            trigger: The resume trigger (unused).

        Returns:
            A ``HandlerResult`` describing the outcome.
        """
        return self.on_enter(ctx, state)
