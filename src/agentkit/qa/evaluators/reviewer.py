"""Semantic QA layer -- LLM-based code review.

Defines the contract. Actual LLM implementation comes later.
``SemanticReviewer`` is a passthrough that always passes (for pipeline
testing until the real LLM integration is available).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.qa.prompt_audit import materialize_qa_prompt_audit
from agentkit.qa.protocols import LayerResult

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext


class SemanticReviewer:
    """Layer 2: LLM-based semantic review.

    Currently a passthrough that always passes. Real implementation
    will call an LLM for code review, test coverage analysis, and
    acceptance criteria verification.

    Satisfies the :class:`~agentkit.qa.protocols.QALayer` protocol.
    """

    @property
    def name(self) -> str:
        """Return the layer name.

        Returns:
            ``"semantic"``.
        """
        return "semantic"

    def evaluate(self, ctx: StoryContext, story_dir: Path) -> LayerResult:
        """Evaluate semantic quality -- currently a passthrough.

        Args:
            ctx: Story context (unused in passthrough).
            story_dir: Directory containing story artifacts (unused).

        Returns:
            LayerResult with ``passed=True`` and no findings.
        """
        return LayerResult(
            layer=self.name,
            passed=True,
            metadata={
                "prompt_audit": materialize_qa_prompt_audit(
                    layer_name=self.name,
                    template_name="qa-semantic-review",
                    ctx=ctx,
                    story_dir=story_dir,
                ),
            },
        )
