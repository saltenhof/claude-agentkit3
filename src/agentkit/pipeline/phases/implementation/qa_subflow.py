"""Implementation QA-subflow cycle orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.qa.remediation.feedback import build_feedback

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.qa.policy_engine.engine import PolicyEngine, VerifyDecision
    from agentkit.qa.protocols import QALayer
    from agentkit.qa.remediation.feedback import RemediationFeedback
    from agentkit.story_context_manager.models import StoryContext


@dataclass(frozen=True)
class QaSubflowCycleResult:
    """Result of one implementation QA-subflow cycle."""

    decision: VerifyDecision
    feedback: RemediationFeedback | None
    attempt_nr: int


class QaSubflowCycle:
    """Orchestrate one round of implementation QA evaluation."""

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
    ) -> QaSubflowCycleResult:
        """Execute one implementation QA-subflow cycle."""

        results = [layer.evaluate(ctx, story_dir) for layer in self._layers]
        decision = self._policy.decide(results)
        feedback = build_feedback(decision, ctx.story_id, attempt_nr)
        return QaSubflowCycleResult(
            decision=decision,
            feedback=feedback,
            attempt_nr=attempt_nr,
        )
