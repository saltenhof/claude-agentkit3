"""Verify cycle -- orchestrates QA layers and policy engine.

Orchestration only (ARCH-12). Business logic lives in the individual
layers and the policy engine. This module connects them and produces
a single-cycle result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.qa.remediation.feedback import build_feedback

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.qa.policy_engine.engine import PolicyEngine, VerifyDecision
    from agentkit.qa.protocols import QALayer
    from agentkit.qa.remediation.feedback import RemediationFeedback
    from agentkit.story.models import StoryContext


@dataclass(frozen=True)
class VerifyCycleResult:
    """Result of one verify cycle.

    Immutable value object (ARCH-29).

    Args:
        decision: The policy engine's final decision.
        feedback: Remediation feedback if the decision was FAIL,
            otherwise ``None``.
        attempt_nr: Which attempt this cycle represents.
    """

    decision: VerifyDecision
    feedback: RemediationFeedback | None
    attempt_nr: int


class VerifyCycle:
    """Orchestrates one round of QA evaluation.

    Steps:
        1. Run all configured QA layers.
        2. Feed results to the PolicyEngine.
        3. If FAIL: build RemediationFeedback.
        4. Return VerifyCycleResult.

    No business logic beyond orchestration (ARCH-12).
    """

    def __init__(
        self,
        layers: list[QALayer],
        policy_engine: PolicyEngine,
    ) -> None:
        self._layers = layers
        self._policy = policy_engine

    def run(
        self,
        ctx: StoryContext,
        story_dir: Path,
        attempt_nr: int = 1,
    ) -> VerifyCycleResult:
        """Execute one verify cycle.

        All layers run unconditionally. Their results are aggregated
        by the policy engine into a single decision.

        Args:
            ctx: Story context for the current pipeline run.
            story_dir: Directory containing story artifacts.
            attempt_nr: Current attempt number (1-based).

        Returns:
            A ``VerifyCycleResult`` with decision and optional feedback.
        """
        # 1. Run all layers
        results = [layer.evaluate(ctx, story_dir) for layer in self._layers]

        # 2. Policy decision
        decision = self._policy.decide(results)

        # 3. Build feedback if failed
        feedback = build_feedback(decision, ctx.story_id, attempt_nr)

        return VerifyCycleResult(
            decision=decision,
            feedback=feedback,
            attempt_nr=attempt_nr,
        )
