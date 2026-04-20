"""Unit tests for the setup phase context builder.

Uses monkeypatch on ``get_issue`` to avoid real GitHub CLI calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.integrations.github.issues import IssueData
from agentkit.pipeline.phases.setup.context_builder import (
    _extract_story_type,
    build_story_context,
)
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _make_issue(
    *,
    number: int = 42,
    title: str = "Add widget feature",
    state: str = "OPEN",
    labels: tuple[str, ...] = (),
    body: str = "Issue body",
    url: str = "https://github.com/owner/repo/issues/42",
) -> IssueData:
    """Create an ``IssueData`` for testing."""
    return IssueData(
        number=number,
        title=title,
        state=state,
        body=body,
        labels=labels,
        url=url,
    )


class TestExtractStoryType:
    """Tests for label-based story type extraction."""

    def test_bug_label(self) -> None:
        """Label ``"bug"`` maps to BUGFIX."""
        assert _extract_story_type(("bug",)) == StoryType.BUGFIX

    def test_bugfix_label(self) -> None:
        """Label ``"bugfix"`` maps to BUGFIX."""
        assert _extract_story_type(("bugfix",)) == StoryType.BUGFIX

    def test_concept_label(self) -> None:
        """Label ``"concept"`` maps to CONCEPT."""
        assert _extract_story_type(("concept",)) == StoryType.CONCEPT

    def test_research_label(self) -> None:
        """Label ``"research"`` maps to RESEARCH."""
        assert _extract_story_type(("research",)) == StoryType.RESEARCH

    def test_no_match_defaults_to_implementation(self) -> None:
        """No recognised label defaults to IMPLEMENTATION."""
        assert _extract_story_type(("enhancement", "docs")) == StoryType.IMPLEMENTATION

    def test_empty_labels_defaults_to_implementation(self) -> None:
        """Empty labels default to IMPLEMENTATION."""
        assert _extract_story_type(()) == StoryType.IMPLEMENTATION

    def test_case_insensitive(self) -> None:
        """Label matching is case-insensitive."""
        assert _extract_story_type(("BUG",)) == StoryType.BUGFIX
        assert _extract_story_type(("Concept",)) == StoryType.CONCEPT
        assert _extract_story_type(("RESEARCH",)) == StoryType.RESEARCH


class TestBuildStoryContext:
    """Tests for ``build_story_context``."""

    def test_bug_label_produces_bugfix_type(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """Label ``"bug"`` results in StoryType.BUGFIX."""
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=("bug",)),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        assert ctx.story_type == StoryType.BUGFIX
        assert ctx.implementation_contract is None

    def test_concept_label_produces_concept_type(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """Label ``"concept"`` results in StoryType.CONCEPT."""
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=("concept",)),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        assert ctx.story_type == StoryType.CONCEPT
        assert ctx.implementation_contract is None

    def test_research_label_produces_research_type(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """Label ``"research"`` results in StoryType.RESEARCH."""
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=("research",)),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        assert ctx.story_type == StoryType.RESEARCH
        assert ctx.implementation_contract is None

    def test_no_label_defaults_to_implementation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """No recognised label defaults to IMPLEMENTATION."""
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=("enhancement",)),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        assert ctx.story_type == StoryType.IMPLEMENTATION
        assert ctx.implementation_contract == ImplementationContract.STANDARD

    def test_story_id_generated_from_issue_nr(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """story_id is derived as ``"STORY-{issue_nr}"`` when not provided."""
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(number=42),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        assert ctx.story_id == "STORY-42"

    def test_explicit_story_id_is_used(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """Explicit story_id overrides the auto-generated one."""
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(),
        )
        ctx = build_story_context(
            "owner", "repo", 42, tmp_path, "test-project", story_id="CUSTOM-99",
        )
        assert ctx.story_id == "CUSTOM-99"

    def test_context_fields_are_populated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """All key StoryContext fields are correctly populated."""
        issue = _make_issue(
            number=42,
            title="Add widget feature",
            labels=("bug", "priority:high"),
        )
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.context_builder.get_issue",
            lambda owner, repo, nr: issue,
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")

        assert ctx.issue_nr == 42
        assert ctx.title == "Add widget feature"
        assert ctx.project_root == tmp_path
        assert "owner/repo" in ctx.participating_repos
        assert "bug" in ctx.labels
        assert "priority:high" in ctx.labels
        assert ctx.created_at is not None

    def test_mode_from_profile_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """Mode is set from the story type profile's default_mode."""
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.context_builder.get_issue",
            lambda owner, repo, nr: _make_issue(labels=("concept",)),
        )
        ctx = build_story_context("owner", "repo", 42, tmp_path, "test-project")
        # Concept profile's default mode is NOT_APPLICABLE
        assert ctx.execution_route == StoryMode.NOT_APPLICABLE
