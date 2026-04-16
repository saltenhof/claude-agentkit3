"""Adversarial QA layer -- edge-case testing and multi-LLM sparring.

Defines the contract. Actual LLM implementation comes later.
``AdversarialChallenger`` is a passthrough that always passes (for
pipeline testing until the real multi-LLM integration is available).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.qa.protocols import LayerResult

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext


class AdversarialChallenger:
    """Layer 3: Adversarial edge-case testing.

    Currently a passthrough that always passes. Real implementation
    will generate edge-case tests, run them, and perform multi-LLM
    sparring over weaknesses (code stories only).

    Satisfies the :class:`~agentkit.qa.protocols.QALayer` protocol.
    """

    @property
    def name(self) -> str:
        """Return the layer name.

        Returns:
            ``"adversarial"``.
        """
        return "adversarial"

    def evaluate(self, ctx: StoryContext, story_dir: Path) -> LayerResult:
        """Evaluate adversarial quality -- currently a passthrough.

        Args:
            ctx: Story context (unused in passthrough).
            story_dir: Directory containing story artifacts (unused).

        Returns:
            LayerResult with ``passed=True`` and no findings.
        """
        return LayerResult(layer=self.name, passed=True)
