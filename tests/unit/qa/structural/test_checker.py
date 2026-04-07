"""Tests for StructuralChecker -- the structural QA layer."""

from __future__ import annotations

import json

from agentkit.qa.protocols import QALayer, Severity
from agentkit.qa.structural.checker import StructuralChecker
from agentkit.story.models import StoryContext
from agentkit.story.types import StoryMode, StoryType


def _make_context(
    story_type: StoryType = StoryType.BUGFIX,
) -> StoryContext:
    """Build a minimal StoryContext for testing."""
    return StoryContext(
        story_id="TEST-001",
        story_type=story_type,
        mode=StoryMode.EXECUTION,
    )


def _setup_complete_story_dir(
    tmp_path: object,
    story_type: StoryType = StoryType.BUGFIX,
) -> object:
    """Set up a story dir with all required artifacts for a given type.

    Returns the story_dir Path.
    """
    from pathlib import Path

    story_dir = Path(str(tmp_path))

    # context.json
    ctx_data = {
        "story_id": "TEST-001",
        "story_type": story_type.value,
        "mode": StoryMode.EXECUTION.value,
    }
    (story_dir / "context.json").write_text(json.dumps(ctx_data))

    # Phase snapshots for all phases before verify
    from agentkit.story.types import get_profile

    profile = get_profile(story_type)
    for phase in profile.phases:
        if phase == "verify":
            break
        (story_dir / f"phase-state-{phase}.json").write_text(
            json.dumps({"story_id": "TEST-001", "phase": phase, "status": "completed"}),
        )

    return story_dir


class TestStructuralChecker:
    """StructuralChecker layer tests."""

    def test_complete_setup_passes(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(_setup_complete_story_dir(tmp_path)))
        checker = StructuralChecker()
        ctx = _make_context()
        result = checker.evaluate(ctx, story_dir)
        assert result.passed is True
        assert result.layer == "structural"

    def test_missing_context_fails(self, tmp_path: object) -> None:
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        checker = StructuralChecker()
        ctx = _make_context()
        result = checker.evaluate(ctx, story_dir)
        assert result.passed is False
        assert any(
            f.severity == Severity.CRITICAL and f.check == "context_exists"
            for f in result.findings
        )

    def test_collects_all_findings_no_early_return(self, tmp_path: object) -> None:
        """All checks run even if earlier ones fail."""
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        # No context, no snapshots -- both should produce findings
        checker = StructuralChecker()
        ctx = _make_context()
        result = checker.evaluate(ctx, story_dir)
        assert result.passed is False
        # Should have context_exists finding AND phase_snapshots findings
        checks_found = {f.check for f in result.findings}
        assert "context_exists" in checks_found
        # Phase snapshot findings should also be present
        assert "phase_snapshots" in checks_found

    def test_implements_qa_layer_protocol(self) -> None:
        checker = StructuralChecker()
        assert isinstance(checker, QALayer)

    def test_name_is_structural(self) -> None:
        checker = StructuralChecker()
        assert checker.name == "structural"

    def test_implementation_story_checks_more_phases(self, tmp_path: object) -> None:
        """Implementation stories require more phase snapshots than bugfix."""
        from pathlib import Path

        story_dir = Path(str(tmp_path))
        ctx_data = {
            "story_id": "TEST-001",
            "story_type": StoryType.IMPLEMENTATION.value,
            "mode": StoryMode.EXPLORATION.value,
        }
        (story_dir / "context.json").write_text(json.dumps(ctx_data))
        # Only setup snapshot, missing exploration + implementation
        (story_dir / "phase-state-setup.json").write_text("{}")

        checker = StructuralChecker()
        ctx = StoryContext(
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            mode=StoryMode.EXPLORATION,
        )
        result = checker.evaluate(ctx, story_dir)
        assert result.passed is False
        # Should have findings for missing exploration and implementation snapshots
        snapshot_findings = [
            f for f in result.findings if f.check == "phase_snapshots"
        ]
        assert len(snapshot_findings) >= 2
