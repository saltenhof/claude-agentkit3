"""Tests for prompt composition."""

from __future__ import annotations

from pathlib import Path

from agentkit.prompt_composer.composer import (
    ComposeConfig,
    ComposedPrompt,
    compose_prompt,
    write_prompt,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType


def _make_context(
    *,
    story_id: str = "AG3-001",
    story_type: StoryType = StoryType.IMPLEMENTATION,
    mode: StoryMode = StoryMode.EXECUTION,
    issue_nr: int = 42,
    title: str = "Add widget feature",
    project_root: Path | None = Path("/tmp/project"),
) -> StoryContext:
    """Build a minimal StoryContext for testing."""
    return StoryContext(
        story_id=story_id,
        story_type=story_type,
        mode=mode,
        issue_nr=issue_nr,
        title=title,
        project_root=project_root,
    )


class TestComposePrompt:
    """Tests for compose_prompt()."""

    def test_implementation_contains_story_id(self) -> None:
        """Composed implementation prompt must contain the story ID."""
        ctx = _make_context()
        config = ComposeConfig(story_type=StoryType.IMPLEMENTATION)
        result = compose_prompt(ctx, config)
        assert "AG3-001" in result.content

    def test_implementation_contains_title(self) -> None:
        """Composed implementation prompt must contain the title."""
        ctx = _make_context()
        config = ComposeConfig(story_type=StoryType.IMPLEMENTATION)
        result = compose_prompt(ctx, config)
        assert "Add widget feature" in result.content

    def test_implementation_contains_issue_nr(self) -> None:
        """Composed implementation prompt must contain the issue number."""
        ctx = _make_context()
        config = ComposeConfig(story_type=StoryType.IMPLEMENTATION)
        result = compose_prompt(ctx, config)
        assert "#42" in result.content

    def test_bugfix_contains_bugfix_marker(self) -> None:
        """Composed bugfix prompt must contain 'Bugfix' in its text."""
        ctx = _make_context(story_type=StoryType.BUGFIX)
        config = ComposeConfig(story_type=StoryType.BUGFIX)
        result = compose_prompt(ctx, config)
        assert "Bugfix" in result.content

    def test_prompt_contains_sentinel(self) -> None:
        """Every composed prompt must contain a sentinel marker."""
        ctx = _make_context()
        config = ComposeConfig(story_type=StoryType.IMPLEMENTATION)
        result = compose_prompt(ctx, config)
        assert "[SENTINEL:" in result.content
        assert len(result.sentinel) > 0

    def test_composed_prompt_has_all_fields(self) -> None:
        """ComposedPrompt must populate all four fields."""
        ctx = _make_context()
        config = ComposeConfig(story_type=StoryType.IMPLEMENTATION)
        result = compose_prompt(ctx, config)
        assert isinstance(result, ComposedPrompt)
        assert result.content != ""
        assert result.template_name == "worker-implementation"
        assert result.story_id == "AG3-001"
        assert "SENTINEL" in result.sentinel

    def test_remediation_injects_round_nr(self) -> None:
        """Remediation prompt must contain the round number."""
        ctx = _make_context()
        config = ComposeConfig(
            story_type=StoryType.IMPLEMENTATION,
            spawn_reason="remediation",
            round_nr=3,
            feedback="Fix the off-by-one error",
        )
        result = compose_prompt(ctx, config)
        assert "Runde 3" in result.content

    def test_remediation_injects_feedback(self) -> None:
        """Remediation prompt must contain the QA feedback text."""
        ctx = _make_context()
        config = ComposeConfig(
            story_type=StoryType.IMPLEMENTATION,
            spawn_reason="remediation",
            round_nr=2,
            feedback="Test coverage is below threshold",
        )
        result = compose_prompt(ctx, config)
        assert "Test coverage is below threshold" in result.content

    def test_exploration_mode_selects_exploration_template(self) -> None:
        """Exploration mode must produce the exploration template."""
        ctx = _make_context(mode=StoryMode.EXPLORATION)
        config = ComposeConfig(
            story_type=StoryType.IMPLEMENTATION,
            mode=StoryMode.EXPLORATION,
        )
        result = compose_prompt(ctx, config)
        assert result.template_name == "worker-exploration"
        assert "Exploration" in result.content

    def test_concept_type(self) -> None:
        """Concept type must select the concept template."""
        ctx = _make_context(
            story_type=StoryType.CONCEPT,
            mode=StoryMode.NOT_APPLICABLE,
        )
        config = ComposeConfig(story_type=StoryType.CONCEPT)
        result = compose_prompt(ctx, config)
        assert result.template_name == "worker-concept"
        assert "Konzeptdokument" in result.content

    def test_research_type(self) -> None:
        """Research type must select the research template."""
        ctx = _make_context(
            story_type=StoryType.RESEARCH,
            mode=StoryMode.NOT_APPLICABLE,
        )
        config = ComposeConfig(story_type=StoryType.RESEARCH)
        result = compose_prompt(ctx, config)
        assert result.template_name == "worker-research"
        assert "Recherchiere" in result.content


class TestWritePrompt:
    """Tests for write_prompt()."""

    def test_writes_file_with_correct_name(
        self,
        tmp_path: Path,
    ) -> None:
        """write_prompt must create a file with the naming convention."""
        ctx = _make_context()
        config = ComposeConfig(story_type=StoryType.IMPLEMENTATION)
        prompt = compose_prompt(ctx, config)

        path = write_prompt(prompt, tmp_path)

        assert path.exists()
        assert path.name == "worker-implementation--initial--r1.md"
        content = path.read_text(encoding="utf-8")
        assert content == prompt.content

    def test_writes_remediation_filename(
        self,
        tmp_path: Path,
    ) -> None:
        """write_prompt for remediation must reflect spawn_reason and round."""
        ctx = _make_context()
        config = ComposeConfig(
            story_type=StoryType.IMPLEMENTATION,
            spawn_reason="remediation",
            round_nr=2,
            feedback="Fix issues",
        )
        prompt = compose_prompt(ctx, config)

        path = write_prompt(
            prompt,
            tmp_path,
            spawn_reason="remediation",
            round_nr=2,
        )

        assert path.name == "worker-remediation--remediation--r2.md"
        assert path.exists()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """write_prompt must create parent directories if needed."""
        output_dir = tmp_path / "nested" / "dir"
        ctx = _make_context()
        config = ComposeConfig(story_type=StoryType.BUGFIX)
        prompt = compose_prompt(ctx, config)

        path = write_prompt(prompt, output_dir)

        assert path.exists()
        assert path.parent == output_dir
