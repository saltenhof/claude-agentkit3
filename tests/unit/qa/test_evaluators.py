"""Tests for SemanticReviewer -- passthrough LLM layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.qa.evaluators.reviewer import SemanticReviewer

if TYPE_CHECKING:
    from pathlib import Path
from agentkit.qa.protocols import QALayer
from agentkit.story.models import StoryContext
from agentkit.story.types import StoryMode, StoryType


class TestSemanticReviewer:
    """SemanticReviewer passthrough tests."""

    def test_evaluate_returns_passed(self, tmp_path: Path) -> None:
        reviewer = SemanticReviewer()
        ctx = StoryContext(
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            mode=StoryMode.EXECUTION,
        )
        result = reviewer.evaluate(ctx, tmp_path)
        assert result.passed is True
        assert result.layer == "semantic"
        assert result.findings == ()

    def test_implements_qa_layer_protocol(self) -> None:
        reviewer = SemanticReviewer()
        assert isinstance(reviewer, QALayer)

    def test_name_is_semantic(self) -> None:
        reviewer = SemanticReviewer()
        assert reviewer.name == "semantic"
