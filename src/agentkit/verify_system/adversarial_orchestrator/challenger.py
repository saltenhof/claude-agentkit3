"""Adversarial QA layer -- edge-case testing and multi-LLM sparring.

Defines the contract. Actual LLM implementation comes later.
``AdversarialChallenger`` is a passthrough that always passes (for
pipeline testing until the real multi-LLM integration is available).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.verify_system.prompt_audit_support import PromptAuditMixin
from agentkit.verify_system.protocols import LayerResult

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput


class AdversarialChallenger(PromptAuditMixin):
    """Layer 3: Adversarial edge-case testing.

    Currently a passthrough that always passes. Real implementation
    will generate edge-case tests, run them, and perform multi-LLM
    sparring over weaknesses (code stories only).

    Satisfies the :class:`~agentkit.verify_system.protocols.QALayer` protocol.
    """

    @property
    def name(self) -> str:
        """Return the layer name.

        Returns:
            ``"adversarial"``.
        """
        return "adversarial"

    def evaluate(
        self,
        ctx: StoryContext,
        story_dir: Path,
        *,
        review_input: Layer2ReviewInput | None = None,
    ) -> LayerResult:
        """Evaluate adversarial quality -- currently a passthrough.

        ``review_input`` is accepted but ignored by Layer 3 (Adversarial);
        it is only used by Layer-2 reviewers.

        Args:
            ctx: Story context (unused in passthrough).
            story_dir: Directory containing story artifacts (unused).
            review_input: Ignored by Layer 3. Accepted for protocol
                compatibility with ``QALayer``.

        Returns:
            LayerResult with ``passed=True`` and no findings.
        """
        del review_input  # Layer 3 does not use review_input.
        return LayerResult(
            layer=self.name,
            passed=True,
            metadata={
                "prompt_audit": self._materialize_prompt_audit(
                    layer_name=self.name,
                    template_name="qa-adversarial-review",
                    ctx=ctx,
                    story_dir=story_dir,
                ),
            },
        )
