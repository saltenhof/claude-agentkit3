"""Implementation QA-subflow cycle orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.verify_system.remediation.feedback import build_feedback

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system import VerifyDecision, VerifySystem
    from agentkit.verify_system.protocols import QALayer
    from agentkit.verify_system.remediation.feedback import RemediationFeedback


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
        verify_system: VerifySystem,
    ) -> None:
        self._layers = layers
        self._verify_system = verify_system

    def run(
        self,
        ctx: StoryContext,
        story_dir: Path,
        attempt_nr: int = 1,
    ) -> QaSubflowCycleResult:
        """Execute one implementation QA-subflow cycle."""

        results = [layer.evaluate(ctx, story_dir) for layer in self._layers]
        decision = self._verify_system.policy_decision(results)
        feedback = build_feedback(decision, ctx.story_id, attempt_nr)
        return QaSubflowCycleResult(
            decision=decision,
            feedback=feedback,
            attempt_nr=attempt_nr,
        )
