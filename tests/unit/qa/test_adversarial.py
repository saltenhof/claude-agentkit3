"""Tests for AdversarialChallenger -- passthrough adversarial layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.qa.adversarial.challenger import AdversarialChallenger

if TYPE_CHECKING:
    from pathlib import Path
from agentkit.qa.protocols import QALayer
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType


class TestAdversarialChallenger:
    """AdversarialChallenger passthrough tests."""

    def test_evaluate_returns_passed(self, tmp_path: Path) -> None:
        challenger = AdversarialChallenger()
        ctx = StoryContext(
            story_id="TEST-001",
            story_type=StoryType.BUGFIX,
            mode=StoryMode.EXECUTION,
        )
        result = challenger.evaluate(ctx, tmp_path)
        assert result.passed is True
        assert result.layer == "adversarial"
        assert result.findings == ()

    def test_implements_qa_layer_protocol(self) -> None:
        challenger = AdversarialChallenger()
        assert isinstance(challenger, QALayer)

    def test_name_is_adversarial(self) -> None:
        challenger = AdversarialChallenger()
        assert challenger.name == "adversarial"
